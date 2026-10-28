"""Retrieval-augmented generation: parse -> chunk -> embed -> retrieve -> answer."""
import io
import os
import re
from collections import Counter

from .config import settings

SYSTEM_PROMPT = (
    "You answer questions about the user's documents. Use ONLY the numbered sources "
    "provided. Cite every claim with its source number in square brackets, like [1] or "
    "[2][3]. If the sources do not contain the answer, say you could not find it in the "
    "documents instead of guessing. Be concise and direct."
)

OVERVIEW_PROMPT = (
    "The user asked a broad question about their document(s). The numbered sources are the "
    "OPENING passages of each document (title, abstract, introduction), not search results. Use them to "
    "explain what the document is about and its main topic. Cite with source numbers like [1]. "
    "If the opening passages do not make the topic clear, say so instead of guessing."
)

OVERVIEW_PATTERNS = [
    r"\bsummar(y|ise|ize|ies)\b",
    r"\boverview\b",
    r"\btl;?dr\b",
    r"\bmain (idea|point|topic|argument|finding|conclusion)s?\b",
    r"\bwhat('s| is| are) (this|these|the|it)\b.{0,30}\b(about|document|paper|pdf|article)\b",
    r"\b(explain|describe|tell me about) (this|the) (document|paper|pdf|article)\b",
]
_OVERVIEW_RE = re.compile("|".join(OVERVIEW_PATTERNS), re.I)

LIGATURES = str.maketrans({"\ufb01": "fi", "\ufb02": "fl", "\ufb00": "ff", "\ufb03": "ffi", "\ufb04": "ffl"})


def is_overview_question(question: str) -> bool:
    """True for broad questions ('summarize this', 'what is this paper about') that search can't answer."""
    return bool(_OVERVIEW_RE.search(question))

# ---------- parsing & chunking ----------

def _line_key(line: str) -> str:
    key = re.sub(r"^[^\w]+", "", line.strip().lower())
    key = re.sub(r"\d", "#", key)  # page numbers and dates vary, so compare their shape
    return re.sub(r"\s+", " ", key)


def strip_repeated_lines(pages: list[tuple[int, str]], min_pages: int = 5, share: float = 0.4):
    """Drop headers, footers and watermark stamps: lines that repeat on many pages."""
    if len(pages) < min_pages:
        return pages
    counts = Counter()
    for _, text in pages:
        counts.update({_line_key(line) for line in text.splitlines() if line.strip()})
    limit = max(3, int(len(pages) * share))
    junk = {key for key, n in counts.items() if n >= limit}
    return [
        (page, "\n".join(line for line in text.splitlines() if _line_key(line) not in junk))
        for page, text in pages
    ]


def extract_pages(filename: str, data: bytes) -> list[tuple[int, str]]:
    """Return [(page_number, text)]. Plain text files are treated as one page."""
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [
                (i + 1, (page.extract_text() or "").translate(LIGATURES))
                for i, page in enumerate(reader.pages)
            ]
            return strip_repeated_lines(pages)
        except Exception as exc:  # corrupt or encrypted PDF
            raise ValueError("Could not read this PDF. It may be corrupt or password-protected.") from exc
    if ext in {".txt", ".md"}:
        return [(1, data.decode("utf-8", errors="ignore"))]
    raise ValueError("Unsupported file type. Upload a PDF, TXT or MD file.")


def chunk_pages(pages: list[tuple[int, str]], size: int = 180, overlap: int = 40) -> list[dict]:
    """Split each page into overlapping word windows, keeping the page number."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    chunks = []
    for page, text in pages:
        words = re.sub(r"\s+", " ", text).strip().split(" ")
        if not words or words == [""]:
            continue
        step = size - overlap
        for start in range(0, len(words), step):
            piece = words[start : start + size]
            if len(piece) < 15 and start > 0:  # drop tiny trailing fragments
                break
            chunks.append({"page": page, "text": " ".join(piece)})
            if start + size >= len(words):
                break
    return chunks


# ---------- vector store (ChromaDB, lazy so tests don't need it) ----------

_collection = None


def collection():
    global _collection
    if _collection is None:
        import chromadb

        client = chromadb.PersistentClient(path=os.path.join(settings.data_dir, "chroma"))
        _collection = client.get_or_create_collection("chunks", metadata={"hnsw:space": "cosine"})
    return _collection


BATCH_SIZE = 64  # embed a few chunks at a time so big PDFs don't exhaust memory


def index(user_id: int, doc_id: int, filename: str, chunks: list[dict]) -> None:
    col = collection()
    try:
        for start in range(0, len(chunks), BATCH_SIZE):
            batch = chunks[start : start + BATCH_SIZE]
            col.add(
                ids=[f"{doc_id}-{start + i}" for i in range(len(batch))],
                documents=[c["text"] for c in batch],
                metadatas=[
                    {"user_id": user_id, "doc_id": doc_id, "filename": filename, "page": c["page"]}
                    for c in batch
                ],
            )
    except Exception:
        remove(doc_id)  # don't leave half an upload behind
        raise


def remove(doc_id: int) -> None:
    collection().delete(where={"doc_id": doc_id})


def search(user_id: int, question: str, doc_ids: list[int] | None = None) -> list[dict]:
    where = {"user_id": user_id}
    if doc_ids:
        where = {"$and": [{"user_id": user_id}, {"doc_id": {"$in": doc_ids}}]}
    res = collection().query(query_texts=[question], n_results=settings.top_k, where=where)
    out = []
    for text, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        out.append(
            {
                "text": text,
                "filename": meta["filename"],
                "doc_id": meta["doc_id"],
                "page": meta["page"],
                "score": round(1 - dist, 3),  # cosine similarity
            }
        )
    return out


def opening_chunks(doc_ids: list[int], per_doc: int) -> list[dict]:
    """First few chunks of each document (title, abstract, intro), for broad questions."""
    col = collection()
    out = []
    for doc_id in doc_ids:
        res = col.get(ids=[f"{doc_id}-{i}" for i in range(per_doc)])
        rows = sorted(zip(res["ids"], res["documents"], res["metadatas"]), key=lambda r: int(r[0].split("-")[1]))
        for _, text, meta in rows:
            out.append(
                {"text": text, "filename": meta["filename"], "doc_id": doc_id, "page": meta["page"], "score": None}
            )
    return out


# ---------- generation ----------

class LLMError(Exception):
    """Raised when the language model can't be reached or returns an error."""


def generate(question: str, sources: list[dict], history: list[dict], overview: bool = False) -> str:
    import httpx

    context = "\n\n".join(
        f"[{i}] ({s['filename']}, page {s['page']})\n{s['text']}" for i, s in enumerate(sources, 1)
    )
    messages = (
        [{"role": "system", "content": OVERVIEW_PROMPT if overview else SYSTEM_PROMPT}]
        + history
        + [{"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"}]
    )
    try:
        resp = httpx.post(
            f"{settings.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={"model": settings.llm_model, "messages": messages, "temperature": 0.2},
            timeout=180,  # local models can be slow on the first request
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except httpx.ConnectError as exc:
        raise LLMError(
            "Can't reach the language model. If you use Ollama, make sure it is running."
        ) from exc
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        raise LLMError("The language model returned an error. Check LLM_MODEL and LLM_API_KEY.") from exc
