# Marginalia

Ask questions about your own documents and get answers that **cite the exact passage** they came from.
Upload PDFs, text or Markdown files, then chat with them. Select a numbered citation in any answer to read the
original passage highlighted on the page.

**Stack:** FastAPI · React (Vite) · ChromaDB (vector search) · open-source LLM via Ollama · SQLite · JWT auth · Docker · GitHub Actions

**100% free to run:** embeddings and vector search run locally, and the language model is a free open-source model (Ollama) or a free-tier API (Groq, Gemini).

## How it works

```
Upload ──► parse (pypdf) ──► chunk (180 words, 40 overlap, page numbers kept)
                                   │
                                   ▼
                      embed + store in ChromaDB (per-user metadata)
                                   │
Question ──► top-k semantic search (scoped to the user's documents)
                                   │
                                   ▼
          LLM answers ONLY from numbered sources, citing [n]
                                   │
                                   ▼
        UI turns [n] into links that reveal the highlighted passage
```

## Handling broad questions

Similarity search works for specific questions ("What was Marasuchus?") but fails for broad ones ("What is this
paper about?"), because no single passage matches. Marginalia detects this in two ways and answers from the
**opening passages** of the document (title, abstract, introduction) instead:

1. the question looks like a summary request (a small set of patterns in `rag.py`), or
2. the best search hit scores below `OVERVIEW_THRESHOLD` (default 0.18 cosine similarity).

The interface tells the user when this happens. Publisher watermarks, repeating headers and page numbers are
removed before indexing (lines that repeat on many pages), and PDF ligature characters are normalised.

## Features

- Email/password accounts with bcrypt hashing and JWT sessions
- Per-user data isolation (documents, vectors and chat history are all scoped to the owner)
- Page-aware chunking, so every citation says which page it came from
- Search all documents or only the ones you select
- Follow-up questions use recent conversation history
- Grounded answers: the model is told to say "not found" instead of guessing
- Upload validation (type, size, empty/scanned PDFs) with clear error messages
- Responsive layout, dark mode, keyboard-accessible controls
- Automated tests and CI

## Run it (free)

### 1. Get a free language model

**Option A: Ollama (recommended, fully offline, no account).**
Install it from ollama.com, then run once in a terminal:

```bash
ollama pull llama3.2
```

This downloads a ~2 GB model. It needs roughly 4 GB of free RAM.

**Option B: a free API (if your computer is slow).** Create a free key at console.groq.com or
aistudio.google.com, then set `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` as shown in `backend/.env.example`.
Free-tier model names change, so check the provider's model list.

### 2. Start the app

**With Docker**

```bash
docker compose up --build
# open http://localhost:8000
```

**Locally for development**

```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# frontend (new terminal)
cd frontend
npm install
npm run dev                 # http://localhost:5173
```

The first upload downloads a small embedding model (~80 MB) that ChromaDB uses. This happens once.

**Tests:** `cd backend && pytest`

## Evaluating retrieval

Answer quality depends on retrieving the right passage, so the repo includes a small evaluation harness
(`backend/evaluation/`). You give it a document and a list of questions, each with a short phrase that must appear in
the passage that answers it. It then reports, for several chunk sizes:

- **hit@1**: how often the right chunk is the top result
- **hit@5**: how often it is somewhere in the top 5
- **MRR**: a score that rewards ranking the right chunk higher

```bash
# with the app running in Docker, from the project folder
docker compose exec marginalia python -m evaluation.run_eval
docker compose exec marginalia python -m evaluation.run_eval --doc evaluation/mydoc.pdf --questions evaluation/myquestions.json --sizes 60,120,180,300
```

Limitations: matching is by phrase, so a question can be missed if its answer is split across two chunks, and
very short phrases can match the wrong chunk. Use short but distinctive phrases.

### Results

Evaluated on a 55-page scientific paper with 25 questions (written with AI assistance; every answer phrase is
checked against the document text before the run). Each cell is the share of questions where the correct passage
appeared at that position among the top 3 retrieved chunks.

| chunk size (words) | overlap | chunks | hit@1 | hit@3 | MRR |
|---|---|---|---|---|---|
| 60 | 12 | 473 | 48% | 76% | 0.60 |
| 120 | 24 | 247 | 48% | 68% | 0.55 |
| **180** (default) | 36 | 166 | **56%** | 72% | **0.62** |
| 300 | 60 | 107 | 48% | 72% | 0.57 |

**Reading the numbers:** the right passage ranked first for roughly half the questions and in the top 3 for
about three quarters, on a dense paper where many passages sound alike. With 25 questions each question is worth
4 points, so the gaps between chunk sizes (about 2 questions) are within noise. I kept 180 words. Next steps I
would try: hybrid keyword + vector search, a re-ranking step, and a stronger embedding model.

To reproduce with a long PDF of your own: copy it to `backend/evaluation/` (PDFs there are git-ignored, so
you don't redistribute copyrighted papers), write 20+ question/answer-phrase pairs like `dino_questions.json`
(the script refuses to run if an answer phrase is not in the document), then:

```bash
docker compose run --rm marginalia python -m evaluation.run_eval --doc evaluation/mydoc.pdf --questions evaluation/myquestions.json --sizes 60,120,180,300 --k 3
```

## API

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Create account / sign in |
| GET/POST/DELETE | `/api/documents` | List, upload, delete documents |
| POST | `/api/chat` | Ask a question, returns answer + sources |
| GET/DELETE | `/api/history` | Read / clear conversation |

Interactive docs at `/docs` when the server is running.

## Design decisions

- **ChromaDB over a hosted vector DB:** zero setup and persistent on disk, which keeps the project easy to run.
  The `rag.py` module isolates it, so swapping in pgvector or Pinecone touches one file.
- **Word-window chunking with overlap:** simple and predictable, and overlap keeps answers that span a boundary.
- **SQLite:** enough for a single-instance app; the schema moves to Postgres without changes to the queries' shape.
- **Provider-agnostic LLM layer:** the app talks to any OpenAI-compatible endpoint, so it runs on a local model,
  a free API, or a paid one by changing three environment variables.
- **Citations as a first-class feature:** retrieval returns metadata (file, page, score) all the way to the UI.

## Known limitations

- Scanned PDFs (images of pages) have no text layer and are rejected; they need OCR first.
- The broad-question detector is a heuristic, and the 0.18 threshold was chosen from a few manual tests.
  Tune it with `OVERVIEW_THRESHOLD`.
- Evaluation matches answer phrases, so a phrase split across two chunks counts as a miss.
- Small local models give weaker answers than large hosted ones.

## Ideas for next steps

Streaming responses (SSE), hybrid search (BM25 + vectors), a reranking step, OCR for scanned PDFs,
retrieval quality evals (hit rate on a labelled question set), rate limiting, and Postgres + pgvector.
