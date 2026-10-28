from app.rag import chunk_pages


def test_chunking_keeps_page_numbers_and_overlap():
    text = " ".join(f"w{i}" for i in range(400))
    chunks = chunk_pages([(3, text)], size=100, overlap=20)
    assert len(chunks) >= 4
    assert all(c["page"] == 3 for c in chunks)
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-20:] == second[:20]


def test_chunking_skips_empty_pages():
    assert chunk_pages([(1, "   \n  ")]) == []


def test_register_login_and_me(client):
    body = {"email": "A@Example.com", "password": "supersecret1"}
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.post("/api/auth/register", json=body).status_code == 409
    token = client.post("/api/auth/login", json=body).json()["token"]
    r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["email"] == "a@example.com"


def test_wrong_password_rejected(client, auth):
    r = client.post("/api/auth/login", json={"email": "dev@example.com", "password": "nope-nope-1"})
    assert r.status_code == 401


def test_protected_routes_need_token(client):
    assert client.get("/api/documents").status_code == 401
    assert client.post("/api/chat", json={"question": "hi"}).status_code == 401


def test_upload_chat_history_delete(client, auth):
    assert client.post("/api/chat", json={"question": "x"}, headers=auth).status_code == 400
    up = client.post("/api/documents", files={"file": ("a.txt", b"Paris is the capital of France. " * 30)}, headers=auth)
    assert up.status_code == 201
    doc_id = up.json()["id"]

    r = client.post("/api/chat", json={"question": "Capital?"}, headers=auth)
    assert r.status_code == 200 and "[1]" in r.json()["answer"]
    assert len(client.get("/api/history", headers=auth).json()) == 2

    assert client.delete(f"/api/documents/{doc_id}", headers=auth).status_code == 204
    assert client.get("/api/documents", headers=auth).json() == []


def test_rejects_unsupported_file(client, auth):
    r = client.post("/api/documents", files={"file": ("x.exe", b"nope")}, headers=auth)
    assert r.status_code == 400


def test_users_cannot_delete_each_others_documents(client, auth):
    doc = client.post("/api/documents", files={"file": ("a.txt", b"hello world " * 40)}, headers=auth).json()
    other = client.post("/api/auth/register", json={"email": "b@example.com", "password": "supersecret1"}).json()
    r = client.delete(f"/api/documents/{doc['id']}", headers={"Authorization": f"Bearer {other['token']}"})
    assert r.status_code == 404


def test_generate_calls_openai_compatible_endpoint(monkeypatch):
    import httpx
    from app import rag

    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, json=json)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": " Paris [1] "}}]},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    src = [{"text": "Paris is the capital.", "filename": "a.txt", "page": 1}]
    assert rag.generate("Capital?", src, []) == "Paris [1]"
    assert captured["url"].endswith("/chat/completions")
    assert captured["json"]["messages"][0]["role"] == "system"


def test_generate_reports_model_down(monkeypatch):
    import httpx
    import pytest
    from app import rag

    def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(rag.LLMError, match="Ollama"):
        rag.generate("q", [{"text": "t", "filename": "a", "page": 1}], [])


def test_index_adds_in_small_batches_with_unique_ids(monkeypatch):
    from app import rag

    calls = []

    class FakeCollection:
        def add(self, ids, documents, metadatas):
            calls.append(ids)

        def delete(self, where):
            pass

    monkeypatch.setattr(rag, "collection", lambda: FakeCollection())
    chunks = [{"page": 1, "text": f"chunk {i}"} for i in range(150)]
    rag.index(1, 7, "big.pdf", chunks)
    assert len(calls) == 3 and max(len(c) for c in calls) == rag.BATCH_SIZE
    all_ids = [i for c in calls for i in c]
    assert len(all_ids) == len(set(all_ids)) == 150


def test_overview_question_detection():
    from app.rag import is_overview_question

    for q in ["What is this document about?", "Summarize this paper", "give me an overview", "What is the main idea?", "tl;dr"]:
        assert is_overview_question(q), q
    for q in ["What is the Ischigualasto Formation?", "How much does a card cost?", "When did dinosaurs first appear?"]:
        assert not is_overview_question(q), q


def test_strip_repeated_lines_removes_headers_but_keeps_body():
    from app.rag import strip_repeated_lines

    stamp = "Downloaded from example.org 10:31:08"
    topics = ["herons", "granite", "tides", "maple", "copper", "lichen", "basalt", "otters"]
    pages = [(i, f"{stamp}\n{400 + i} AUTHOR\nA paragraph about {t}.") for i, t in enumerate(topics, 1)]
    cleaned = dict(strip_repeated_lines(pages))
    assert all(stamp not in t and "AUTHOR" not in t for t in cleaned.values())
    assert "A paragraph about maple." in cleaned[4]


def test_short_documents_are_left_alone():
    from app.rag import strip_repeated_lines

    pages = [(1, "same line\nbody one"), (2, "same line\nbody two")]
    assert strip_repeated_lines(pages) == pages


def test_broad_question_uses_opening_passages_not_search(client, auth, monkeypatch):
    from app import rag

    client.post("/api/documents", files={"file": ("a.txt", b"hello world " * 40)}, headers=auth)
    monkeypatch.setattr(rag, "search", lambda *a, **k: (_ for _ in ()).throw(AssertionError("search must not run")))
    r = client.post("/api/chat", json={"question": "What is this document about?"}, headers=auth)
    assert r.status_code == 200
    assert r.json()["mode"] == "overview" and r.json()["sources"][0]["score"] is None


def test_weak_search_falls_back_to_opening_passages(client, auth, monkeypatch):
    from app import rag

    client.post("/api/documents", files={"file": ("a.txt", b"hello world " * 40)}, headers=auth)
    weak = [{"text": "x", "filename": "a.txt", "doc_id": 1, "page": 1, "score": 0.05}]
    monkeypatch.setattr(rag, "search", lambda *a, **k: weak)
    r = client.post("/api/chat", json={"question": "something vague"}, headers=auth)
    assert r.json()["mode"] == "overview"


def test_specific_question_still_uses_search(client, auth):
    client.post("/api/documents", files={"file": ("a.txt", b"hello world " * 40)}, headers=auth)
    r = client.post("/api/chat", json={"question": "Capital?"}, headers=auth)
    assert r.json()["mode"] == "search"


def test_opening_chunks_returns_first_chunks_in_order(monkeypatch):
    from app import rag

    class Fake:
        def get(self, ids):
            return {
                "ids": ["7-2", "7-0", "7-1"],
                "documents": ["third", "first", "second"],
                "metadatas": [{"filename": "f.pdf", "page": 2}, {"filename": "f.pdf", "page": 1}, {"filename": "f.pdf", "page": 1}],
            }

    monkeypatch.setattr(rag, "collection", lambda: Fake())
    out = rag.opening_chunks([7], per_doc=3)
    assert [c["text"] for c in out] == ["first", "second", "third"]
    assert all(c["score"] is None for c in out)
