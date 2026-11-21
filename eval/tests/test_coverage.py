"""Coverage check (Part E2/E4) with a fake embedder: no model, no network."""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from query_coverage import coverage, read_jsonl  # noqa: E402

HERE = Path(__file__).resolve().parents[1]


def fake_embed(texts):
    out = []
    for text in texts:
        vec = [0.0] * 128
        for word in text.lower().replace("?", "").split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 128] += 1.0
        out.append(vec)
    return out


def test_live_queries_file_meets_the_assignment():
    live = read_jsonl(HERE / "live_queries.jsonl")
    assert len(live) >= 40
    assert sum(1 for q in live if q["topic"] in ("hostel", "transport", "admissions", "cafeteria")) >= 12


def test_identical_query_is_covered_and_unrelated_is_not():
    golden = [{"id": "g1", "question": "What CGPA avoids academic warning"}]
    live = [{"id": "a", "query": "What CGPA avoids academic warning", "topic": "standing"},
            {"id": "b", "query": "which bus goes to campus", "topic": "transport"}]
    result = coverage(live, golden, fake_embed, threshold=0.8)
    assert [r["covered"] for r in result["rows"]] == [True, False]
    assert result["coverage"] == 0.5 and result["uncovered_by_topic"] == {"transport": ["b"]}


def test_more_golden_questions_raise_coverage():
    live = [{"id": "b", "query": "which bus goes to campus", "topic": "transport"}]
    before = coverage(live, [{"id": "g1", "question": "What CGPA avoids warning"}], fake_embed, 0.8)
    after = coverage(live, [{"id": "g1", "question": "What CGPA avoids warning"},
                            {"id": "g2", "question": "which bus goes to campus"}], fake_embed, 0.8)
    assert before["coverage"] < after["coverage"]
