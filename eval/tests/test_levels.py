"""Module and component levels, with a fake embedder and hand-made rows (no model, no api)."""

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from levels.component import ndcg_at_k, reciprocal_rank, score  # noqa: E402
from levels.module import load_pairs, measure  # noqa: E402


def fake_embed(texts):
    out = []
    for text in texts:
        vec = [0.0] * 64
        for word in text.lower().split():
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
        out.append(vec)
    return out


def test_module_level_reports_gap_timing_and_determinism():
    m = measure(fake_embed, load_pairs())
    assert m["paraphrase_pairs"] >= 15 and m["unrelated_pairs"] >= 15
    assert m["determinism_max_abs_diff"] == 0.0
    assert m["embed_ms_per_chunk"] >= 0
    assert m["cosine_gap"] == round(m["mean_cosine_paraphrase"] - m["mean_cosine_unrelated"], 4)


def test_reciprocal_rank_and_ndcg():
    assert reciprocal_rank([0, 0, 1, 0, 0]) == 1 / 3
    assert reciprocal_rank([0, 0, 0]) == 0.0
    assert ndcg_at_k([1, 0, 0, 0, 0], n_relevant=1) == 1.0
    assert 0 < ndcg_at_k([0, 1, 0, 0, 0], n_relevant=1) < 1


def test_component_scores_only_questions_with_relevant_passages():
    rel = [{"source": "rules.pdf", "section": "Attendance"}]
    questions = [{"id": "a", "type": "answerable", "relevant": rel},
                 {"id": "b", "type": "unanswerable", "relevant": []}]
    rows = [{"id": "a", "retrieved": [{"source": "other.pdf", "section": "X"},
                                      {"source": "rules.pdf", "section": "1.21 Attendance"}]},
            {"id": "b", "retrieved": [{"source": "rules.pdf", "section": "Attendance"}]}]
    result = score(questions, rows)
    assert result["scored_questions"] == 1
    assert result["recall@3"] == 1.0 and result["mrr"] == 0.5
