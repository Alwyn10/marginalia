"""Retrieval evaluation: does the right passage show up in the top results?

For every question you provide a short phrase ("answer") that must appear in the passage
that answers it. A question counts as a hit if any of the top-k retrieved chunks contains
that phrase. The script compares several chunk sizes so you can pick settings with data.

Run from the backend folder:
    python -m evaluation.run_eval
    python -m evaluation.run_eval --doc my_doc.txt --questions my_questions.json --sizes 60,120,180,300
"""
import argparse
import json
import os
import sys
import uuid

from app.rag import chunk_pages, extract_pages

HERE = os.path.dirname(__file__)


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def rank_of_answer(retrieved: list[str], answer: str) -> int | None:
    """1-based position of the first retrieved chunk containing the answer phrase."""
    target = normalize(answer)
    for position, chunk in enumerate(retrieved, 1):
        if target in normalize(chunk):
            return position
    return None


def score(ranks: list[int | None], k: int) -> dict:
    n = len(ranks)
    found = [r for r in ranks if r is not None and r <= k]
    return {
        "hit@1": sum(1 for r in ranks if r == 1) / n,
        f"hit@{k}": len(found) / n,
        "mrr": sum(1 / r for r in found) / n,  # rewards putting the right chunk first
    }


def chroma_retriever(chunks: list[dict]):
    """Build a throwaway ChromaDB index (same embeddings the app uses)."""
    import chromadb

    col = chromadb.EphemeralClient().create_collection(
        name=f"eval_{uuid.uuid4().hex}", metadata={"hnsw:space": "cosine"}
    )
    col.add(ids=[str(i) for i in range(len(chunks))], documents=[c["text"] for c in chunks])

    def retrieve(question: str, k: int) -> list[str]:
        res = col.query(query_texts=[question], n_results=min(k, len(chunks)))
        return res["documents"][0]

    return retrieve


def evaluate(pages, questions, sizes, overlap_ratio=0.2, k=5, retriever_factory=chroma_retriever):
    rows = []
    for size in sizes:
        overlap = int(size * overlap_ratio)
        chunks = chunk_pages(pages, size=size, overlap=overlap)
        retrieve = retriever_factory(chunks)
        ranks = [rank_of_answer(retrieve(q["question"], k), q["answer"]) for q in questions]
        rows.append({"size": size, "overlap": overlap, "chunks": len(chunks), **score(ranks, k)})
    return rows


def format_table(rows: list[dict], k: int) -> str:
    lines = [
        f"| chunk size | overlap | chunks | hit@1 | hit@{k} | MRR |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['size']} | {r['overlap']} | {r['chunks']} | {r['hit@1']:.0%} | {r[f'hit@{k}']:.0%} | {r['mrr']:.2f} |"
        )
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--doc", default=os.path.join(HERE, "sample_doc.txt"))
    p.add_argument("--questions", default=os.path.join(HERE, "sample_questions.json"))
    p.add_argument("--sizes", default="40,80,120,180,300", help="comma-separated chunk sizes in words")
    p.add_argument("--overlap-ratio", type=float, default=0.2)
    p.add_argument("--k", type=int, default=5)
    args = p.parse_args(argv)

    with open(args.doc, "rb") as f:
        pages = extract_pages(args.doc, f.read())
    with open(args.questions, encoding="utf-8") as f:
        questions = json.load(f)

    # Fail early if a ground-truth phrase is not in the document at all.
    full_text = normalize(" ".join(text for _, text in pages))
    missing = [q["answer"] for q in questions if normalize(q["answer"]) not in full_text]
    if missing:
        print("These answer phrases are not in the document (fix your questions file):", *missing, sep="\n  ")
        return 1

    sizes = [int(s) for s in args.sizes.split(",")]
    print(f"{len(questions)} questions, document has {sum(len(t.split()) for _, t in pages)} words\n")
    rows = evaluate(pages, questions, sizes, args.overlap_ratio, args.k)
    print(format_table(rows, args.k))
    return 0


if __name__ == "__main__":
    sys.exit(main())
