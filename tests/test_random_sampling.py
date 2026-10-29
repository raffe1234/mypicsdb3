"""Regression for large, seeded random selections without full-table random sorting."""
from __future__ import annotations

import pytest

from mypicsdb3.db.catalog import Catalog
from mypicsdb3.random_sampling import random_window_plan


def test_random_window_plan_is_seeded_bounded_and_spread_out():
    assert random_window_plan(20, 0.5) == []
    first = random_window_plan(160, 0.42)
    assert first == random_window_plan(160, 0.42)
    assert first != random_window_plan(160, 0.9)
    assert len(first) == 4
    assert sorted(int(pivot * 4) for pivot, _ in first) == [0, 1, 2, 3]
    assert sum(size for _, size in first) == 160
    assert all(size <= 40 for _, size in first)
    assert random_window_plan(160, "invalid") == random_window_plan(160, 0.0)


def test_random_catalog_uses_distant_key_ranges_without_duplicate_rows(monkeypatch):
    # In-memory stand-in for an ordered, indexed lookup; no full-library scan.
    rows = [{"id": i, "random_key": i / 161.0} for i in range(1, 161)]
    calls = []

    def indexed_rows(where, params, order, limit, offset):
        assert order == "p.random_key" and offset == 0
        assert "random_key" in where
        calls.append(limit)
        threshold = params[0]
        filtered = [r for r in rows if
                    (r["random_key"] >= threshold if ">=" in where
                     else r["random_key"] < threshold)]
        return filtered[:limit]

    catalog = object.__new__(Catalog)
    monkeypatch.setattr(catalog, "_pictures", indexed_rows)
    first = catalog.random_pictures(80, seed=0.31)
    assert first == catalog.random_pictures(80, seed=0.31)
    assert len(first) == len({r["id"] for r in first}) == 80
    assert {int(r["random_key"] * 4) for r in first} == {0, 1, 2, 3}
    assert max(calls) <= 80
    assert catalog.random_pictures(80, seed=0.78) != first


def test_small_random_catalog_keeps_one_pivot(monkeypatch):
    catalog = object.__new__(Catalog)
    calls = []

    def fake_pictures(where, params, order, limit, offset):
        calls.append((where, params, limit))
        return [{"id": 1}]

    monkeypatch.setattr(catalog, "_pictures", fake_pictures)
    assert catalog.random_pictures(1, seed=0.6) == [{"id": 1}]
    assert calls == [("p.random_key>=?", (0.6,), 1)]
