import json
import os
import re
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import rag
from .auth import current_user, hash_password, make_token, verify_password
from .config import settings
from .db import conn, dumps, init

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init()
    yield


app = FastAPI(title="Marginalia", lifespan=lifespan)


# ---------- schemas ----------

class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address.")
        return v


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    doc_ids: list[int] | None = None


# ---------- auth ----------

@app.post("/api/auth/register", status_code=201)
def register(body: Credentials):
    try:
        with conn() as c:
            cur = c.execute(
                "INSERT INTO users(email, password_hash) VALUES (?, ?)",
                (body.email, hash_password(body.password)),
            )
            uid = cur.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(409, "An account with this email already exists.")
    return {"token": make_token(uid), "email": body.email}


@app.post("/api/auth/login")
def login(body: Credentials):
    with conn() as c:
        row = c.execute("SELECT * FROM users WHERE email = ?", (body.email,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect.")
    return {"token": make_token(row["id"]), "email": row["email"]}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


# ---------- documents ----------

@app.get("/api/documents")
def list_documents(user: dict = Depends(current_user)):
    with conn() as c:
        rows = c.execute(
            "SELECT id, filename, chunk_count, created_at FROM documents WHERE user_id = ? ORDER BY id DESC",
            (user["id"],),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/documents", status_code=201)
def upload_document(file: UploadFile, user: dict = Depends(current_user)):
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    try:
        pages = rag.extract_pages(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    chunks = rag.chunk_pages(pages)
    if not chunks:
        raise HTTPException(422, "No readable text found. Scanned PDFs need OCR first.")
    with conn() as c:
        cur = c.execute(
            "INSERT INTO documents(user_id, filename, chunk_count) VALUES (?, ?, ?)",
            (user["id"], file.filename, len(chunks)),
        )
        doc_id = cur.lastrowid
    try:
        rag.index(user["id"], doc_id, file.filename, chunks)
    except Exception:
        with conn() as c:
            c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        raise HTTPException(500, "Indexing failed. Try uploading again.")
    return {"id": doc_id, "filename": file.filename, "chunk_count": len(chunks)}


@app.delete("/api/documents/{doc_id}", status_code=204)
def delete_document(doc_id: int, user: dict = Depends(current_user)):
    with conn() as c:
        row = c.execute(
            "SELECT id FROM documents WHERE id = ? AND user_id = ?", (doc_id, user["id"])
        ).fetchone()
        if not row:
            raise HTTPException(404, "Document not found.")
        c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    rag.remove(doc_id)


# ---------- chat ----------

def _recent_history(user_id: int, limit: int = 6) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    msgs = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    while msgs and msgs[0]["role"] != "user":  # API requires user-first turns
        msgs.pop(0)
    return msgs


@app.post("/api/chat")
def chat(body: ChatIn, user: dict = Depends(current_user)):
    with conn() as c:
        owned = [r["id"] for r in c.execute("SELECT id FROM documents WHERE user_id = ?", (user["id"],))]
    if not owned:
        raise HTTPException(400, "Upload a document first.")
    scope = [d for d in (body.doc_ids or []) if d in owned] or None

    # Broad questions ("summarize this") can't be answered by similarity search, so use the document openings.
    overview = rag.is_overview_question(body.question)
    sources = [] if overview else rag.search(user["id"], body.question, scope)
    if sources and sources[0]["score"] < settings.overview_threshold:
        overview = True
    if overview:
        target = (scope or owned)[:8]
        sources = rag.opening_chunks(target, per_doc=max(1, min(4, 8 // len(target))))
    if not sources:
        raise HTTPException(404, "No matching passages found in your documents.")
    history = _recent_history(user["id"])
    try:
        answer = rag.generate(body.question, sources, history, overview=overview)
    except rag.LLMError as exc:
        raise HTTPException(503, str(exc))

    with conn() as c:
        c.execute("INSERT INTO messages(user_id, role, content) VALUES (?, 'user', ?)", (user["id"], body.question))
        c.execute(
            "INSERT INTO messages(user_id, role, content, sources) VALUES (?, 'assistant', ?, ?)",
            (user["id"], answer, dumps(sources)),
        )
    return {"answer": answer, "sources": sources, "mode": "overview" if overview else "search"}


@app.get("/api/history")
def history(user: dict = Depends(current_user)):
    with conn() as c:
        rows = c.execute(
            "SELECT role, content, sources FROM messages WHERE user_id = ? ORDER BY id", (user["id"],)
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "sources": json.loads(r["sources"] or "[]")}
        for r in rows
    ]


@app.delete("/api/history", status_code=204)
def clear_history(user: dict = Depends(current_user)):
    with conn() as c:
        c.execute("DELETE FROM messages WHERE user_id = ?", (user["id"],))


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the built frontend when present (production / Docker).
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
