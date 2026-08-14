"""
CIE-OS
A01 Blockchain Intelligence Agent

Module:
    intelligence.utils.ranking

Purpose:
    Score ordering and top-N selection helpers.

    Missing (None) key values always sort last in both directions, so
    unscored items can never outrank scored ones.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")

# Sentinel never equal to any real key value.
_NONE_KEY = float("-inf")


def rank_desc(items: Iterable[T], key: Callable[[T], Any]) -> list[T]:
    """
    Return items sorted descending by the given key function.

    Items whose key is None sort last, treating missing values as
    lower than any present value.
    """
    return sorted(
        items,
        key=lambda item: (key(item) is None, _NONE_KEY if key(item) is None else key(item)),
        reverse=True,
    )


def rank_asc(items: Iterable[T], key: Callable[[T], Any]) -> list[T]:
    """
    Return items sorted ascending by the given key function.

    Items whose key is None sort last, treating missing values as
    higher than any present value.
    """
    return sorted(
        items,
        key=lambda item: (key(item) is None, _NONE_KEY if key(item) is None else key(item)),
    )


def top_n(
    items: Iterable[T],
    key: Callable[[T], Any],
    n: int = 10,
    min_key: Any = None,
) -> list[T]:
    """
    Return the top-N items ranked descending by ``key``.

    When ``min_key`` is provided, items whose key is below it are
    excluded before selection. Items with a None key are dropped
    unless ``min_key`` is None.

    Parameters
    ----------
    items
        Iterable of items to rank.
    key
        Key function extracting the sort value from an item.
    n
        Maximum number of results (clamped to >= 0).
    min_key
        Optional inclusive floor for the key value.
    """
    ranked = rank_desc(items, key)
    if min_key is not None:
        ranked = [
            item
            for item in ranked
            if key(item) is not None and key(item) >= min_key
        ]
    return ranked[: max(0, n)]


def top_n_asc(
    items: Iterable[T],
    key: Callable[[T], Any],
    n: int = 10,
    max_key: Any = None,
) -> list[T]:
    """
    Return the bottom-N items ranked ascending by ``key``.

    When ``max_key`` is provided, items whose key is above it are
    excluded before selection.
    """
    ranked = rank_asc(items, key)
    if max_key is not None:
        ranked = [
            item
            for item in ranked
            if key(item) is not None and key(item) <= max_key
        ]
    return ranked[: max(0, n)]
