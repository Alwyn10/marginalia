import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["SECRET_KEY"] = "test-secret"

import pytest
from fastapi.testclient import TestClient

from app import rag
from app.db import conn, init
from app.main import app


@pytest.fixture()
def client(monkeypatch):
    # Keep tests fast and offline: stub the vector store and the LLM.
    store = {}
    monkeypatch.setattr(rag, "index", lambda uid, did, fn, ch: store.setdefault(did, ch))
    monkeypatch.setattr(rag, "remove", lambda did: store.pop(did, None))
    monkeypatch.setattr(
        rag, "search",
        lambda uid, q, ids=None: [{"text": "Paris is the capital.", "filename": "a.txt", "doc_id": 1, "page": 1, "score": 0.9}],
    )
    monkeypatch.setattr(
        rag, "opening_chunks",
        lambda ids, per_doc: [{"text": "Opening passage.", "filename": "a.txt", "doc_id": ids[0], "page": 1, "score": None}],
    )
    monkeypatch.setattr(rag, "generate", lambda q, s, h, overview=False: "The capital is Paris [1].")
    init()
    with conn() as db:  # fresh state for every test
        db.executescript("DELETE FROM messages; DELETE FROM documents; DELETE FROM users;")
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def auth(client):
    r = client.post("/api/auth/register", json={"email": "dev@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {r.json()['token']}"}
