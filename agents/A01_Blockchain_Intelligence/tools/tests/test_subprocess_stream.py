"""
Regression test for a NameError in the subprocess adapter's ``stream()`` path.

``stream()`` wraps its spawn in ``except AdapterError``, but the module imported
only the concrete subclasses -- not the base ``AdapterError``. So any spawn
failure raised ``NameError`` while *evaluating the except clause*, masking the
real error with a confusing one. Found by a pyflakes sweep on 2026-08-22 and
fixed by importing ``AdapterError``.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

import pytest  # noqa: E402

from tools.adapters import AdapterError, AdapterRequest, AdapterValidationError  # noqa: E402
from tools.adapters.subprocess import SubprocessAdapter  # noqa: E402


def test_stream_propagates_adapter_error_from_spawn() -> None:
    adapter = SubprocessAdapter()

    def boom(_params):
        raise AdapterValidationError("bad request", transport=adapter.transport)

    # Force the spawn-failure path that the buggy except clause guarded.
    adapter._spawn = boom  # type: ignore[method-assign]

    request = AdapterRequest(
        method="RUN", path="/bin/true", params={"command": ["true"]}
    )

    # The failure must surface as the AdapterError subclass it started as --
    # never a NameError from an unresolved name in the except clause.
    with pytest.raises(AdapterError) as excinfo:
        list(adapter.stream(request))

    assert isinstance(excinfo.value, AdapterValidationError)


if __name__ == "__main__":
    test_stream_propagates_adapter_error_from_spawn()
    print("subprocess stream regression test passed")
