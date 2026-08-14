"""
Enable ``python -m cli``.

The guard matters: when invoked with ``-m`` this module *is* ``__main__`` and
the CLI runs, but without it any import of ``cli.__main__`` -- by a test
collector, a documentation tool, or a module scanner -- would execute the CLI
against whatever ``sys.argv`` happened to be present.
"""

from __future__ import annotations

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
