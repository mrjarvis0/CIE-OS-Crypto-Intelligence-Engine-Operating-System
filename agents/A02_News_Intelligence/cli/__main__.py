"""
Enable ``python -m agents.A02_News_Intelligence.cli``.

Guard matters: with ``-m`` this module is ``__main__`` and the CLI runs;
without it, an import of ``cli.__main__`` does not execute the CLI.
"""

from __future__ import annotations

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
