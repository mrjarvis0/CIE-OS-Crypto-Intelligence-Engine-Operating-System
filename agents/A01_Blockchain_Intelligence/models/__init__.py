"""
CIE-OS
A01 Blockchain Intelligence Agent

Package:
    models

The model seam. No model is configured: narratives are composed
deterministically, and prompt safety lives in ``prompts/``.

Why this is a redirect and not a second implementation
------------------------------------------------------
This directory names a concept A01 has already built somewhere else. It was
empty, and ``docs/architecture/folder-architecture.md`` section 10 is blunt
about what an empty directory with a name like this invites:

    "an empty directory named ``security/`` invites code to be written in the
    wrong place."

A generated README used to say so in markdown. This package says it in a form
the interpreter checks. ``models.provider`` **is** ``intelligence.narrative.provider`` -- the same
module object, not a copy of its surface -- and every other name is forwarded
live through :func:`__getattr__` rather than re-exported at import time.

Nothing here can go stale, because nothing here is a copy. If the canonical
module is renamed, importing this package fails immediately and by name; if a
function is removed from it, the ``AttributeError`` says which package
redirected and where it pointed. Both are louder failures than a stale
pointer in a markdown file.

Write new code in the canonical module. Adding an implementation here would
recreate exactly the duplication this package exists to prevent.
"""

from __future__ import annotations

from typing import Any

from intelligence.narrative import provider

#: The canonical module. Bound, not copied.
__all__ = ["provider"]


def __getattr__(name: str) -> Any:
    """
    Forward any other name to :mod:`intelligence.narrative.provider`.

    A live delegation rather than a star-import: ``from models import X``
    reads ``intelligence.narrative.provider.X`` at the moment of the call, so this package cannot
    hold a name the canonical module has since dropped.
    """
    try:
        return getattr(provider, name)
    except AttributeError:
        raise AttributeError(
            f"module 'models' has no attribute {name!r}; it redirects to "
            f"'intelligence.narrative.provider', which has no such name"
        ) from None


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(provider)))
