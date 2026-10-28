import json
import os

from app.rag import extract_pages
from evaluation.run_eval import HERE, evaluate, format_table, normalize, rank_of_answer, score

DOC = os.path.join(HERE, "sample_doc.txt")
QUESTIONS = os.path.join(HERE, "sample_questions.json")


def load():
    with open(DOC, "rb") as f:
        pages = extract_pages(DOC, f.read())
    with open(QUESTIONS, encoding="utf-8") as f:
        return pages, json.load(f)


def test_rank_of_answer_is_one_based_and_case_insensitive():
    chunks = ["nothing here", "The fee is   $40 per year", "later"]
    assert rank_of_answer(chunks, "$40") == 2
    assert rank_of_answer(chunks, "the FEE is $40") == 2
    assert rank_of_answer(chunks, "$99") is None


def test_score_metrics():
    s = score([1, 2, None, 7], k=5)
    assert s["hit@1"] == 0.25
    assert s["hit@5"] == 0.5
    assert abs(s["mrr"] - (1 + 0.5) / 4) < 1e-9


def test_every_sample_answer_exists_in_the_sample_document():
    pages, questions = load()
    text = normalize(" ".join(t for _, t in pages))
    assert len(questions) >= 15
    assert all(normalize(q["answer"]) in text for q in questions)


def test_evaluate_with_perfect_and_empty_retrievers():
    pages, questions = load()
    everything = lambda chunks: (lambda q, k: [c["text"] for c in chunks])
    nothing = lambda chunks: (lambda q, k: [])
    perfect = evaluate(pages, questions, [60], k=500, retriever_factory=everything)[0]
    assert perfect["hit@500"] == 1.0
    empty = evaluate(pages, questions, [60], k=5, retriever_factory=nothing)[0]
    assert empty["hit@5"] == 0.0 and empty["mrr"] == 0.0


def test_table_has_one_row_per_size():
    pages, questions = load()
    rows = evaluate(pages, questions, [60, 120], retriever_factory=lambda c: (lambda q, k: []))
    table = format_table(rows, 5)
    assert table.count("\n") == 3 and "| 60 |" in table and "| 120 |" in table
