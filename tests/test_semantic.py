"""Tests for the semantic search maths. No network: embeddings are given by hand."""

import pytest

from backend.app.services.semantic import cosine_similarity, rank_by_similarity


def test_identical_vectors_score_one():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_opposite_vectors_score_minus_one():
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_unrelated_vectors_score_zero():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_scale_does_not_matter():
    assert cosine_similarity([1.0, 1.0], [5.0, 5.0]) == pytest.approx(1.0)


@pytest.mark.parametrize("a, b", [([], []), ([1.0], [1.0, 2.0]), ([0.0, 0.0], [1.0, 1.0])])
def test_degenerate_inputs_score_zero(a, b):
    assert cosine_similarity(a, b) == 0.0


def test_ranking_orders_best_first():
    items = [(1, [0.0, 1.0]), (2, [1.0, 0.1]), (3, [1.0, 0.0])]
    ranked = rank_by_similarity([1.0, 0.0], items)
    assert [doc_id for doc_id, _ in ranked] == [3, 2, 1]


def test_ranking_respects_limit_and_min_score():
    items = [(1, [1.0, 0.0]), (2, [0.9, 0.4]), (3, [0.0, 1.0])]
    assert len(rank_by_similarity([1.0, 0.0], items, limit=2)) == 2
    kept = rank_by_similarity([1.0, 0.0], items, min_score=0.5)
    assert [doc_id for doc_id, _ in kept] == [1, 2]