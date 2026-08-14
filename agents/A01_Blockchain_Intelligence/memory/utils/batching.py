"""
Memory Batching Utilities

Chunk, partition, and window sequences for bulk operations.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Sequence, TypeVar

T = TypeVar("T")


class BatchError(Exception):
    pass


def chunks(
    items: Sequence[T],
    size: int,
) -> list[list[T]]:
    """
    Split a sequence into fixed-size chunks.
    """
    if size < 1:
        raise BatchError("chunk size must be >= 1.")
    return [
        list(items[start : start + size])
        for start in range(0, len(items), size)
    ]


def batched(
    items: Iterable[T],
    size: int,
) -> Iterator[list[T]]:
    """
    Lazily yield fixed-size batches from an iterable.
    """
    if size < 1:
        raise BatchError("batch size must be >= 1.")
    buffer: list[T] = []
    for item in items:
        buffer.append(item)
        if len(buffer) == size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer


def partition(
    items: Sequence[T],
    parts: int,
) -> list[list[T]]:
    """
    Split a sequence into roughly equal parts.
    """
    if parts < 1:
        raise BatchError("parts must be >= 1.")
    if not items:
        return []
    if parts > len(items):
        parts = len(items)
    per_part, remainder = divmod(len(items), parts)
    result: list[list[T]] = []
    index = 0
    for part_index in range(parts):
        size = per_part + (1 if part_index < remainder else 0)
        result.append(list(items[index : index + size]))
        index += size
    return result


def windows(
    items: Sequence[T],
    size: int,
) -> list[list[T]]:
    """
    Sliding windows of a given size over a sequence.
    """
    if size < 1:
        raise BatchError("window size must be >= 1.")
    if size > len(items):
        return []
    return [
        list(items[start : start + size])
        for start in range(len(items) - size + 1)
    ]


def flatten(groups: Iterable[Iterable[T]]) -> list[T]:
    """
    Flatten nested iterables into a single list.
    """
    result: list[T] = []
    for group in groups:
        result.extend(group)
    return result
