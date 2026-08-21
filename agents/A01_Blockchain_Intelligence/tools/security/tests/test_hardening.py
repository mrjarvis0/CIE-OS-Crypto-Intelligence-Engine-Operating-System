"""
CIE-OS
A01 Blockchain Intelligence Agent

Regression tests for `tools.security`.

Every test here names a defect that was present and reachable, not a property
somebody thought would be nice to hold. Each was reproduced against the
shipped code before the fix landed, so each fails on a revert -- which is the
only thing that makes a security test worth its runtime.

The findings, in the order they appear below:

    1. `Authorizer`      a rule dict missing its `permission` key granted
                         every permission, on every tool, to every principal
    2. `Token.expired`   raised ModuleNotFoundError; expiry never enforced
    3. `encryption`      unauthenticated XOR; tampering decrypted silently
    4. `derive_key`      returned a different key each call for one master
    5. `guard`           handed rules the mapping, so no rule saw a value
    6. `RateLimiter`     check and append under separate locks; over-admits
    7. `RateLimiter`     unbounded window map keyed by caller-chosen names
    8. `PermissionError` subclassed the builtin, so `except OSError` ate it
    9. `allow_all()`     granted nothing
   10. `Secret`          pickled and copied in plaintext
   11. `mask_secret`     published the secret's exact length
   12. `IsolationPolicy` mutable after being trusted
   13. `host_allowed`    permitted the cloud metadata endpoint
   14. `Sandbox`         env deny-list missed credential-bearing URL vars
"""

from __future__ import annotations

import base64
import copy
import pickle
import threading

import pytest

from tools.security.auth import (
    AuthenticationError,
    Principal,
    Token,
    TokenAuthenticator,
)
from tools.security.authorization import (
    Authorizer,
    Rule,
    compile_rules,
    deny_rule,
    requirement_rule,
)
from tools.security.encryption import (
    IntegrityError,
    decrypt_bytes,
    decrypt_text,
    derive_key,
    encrypt_bytes,
    encrypt_text,
)
from tools.security.isolation import IsolationPolicy, host_allowed
from tools.security.permissions import (
    PermissionChecker,
    PermissionError,
    allow_all,
    deny_all,
)
from tools.security.rate_limit import RateLimitError, RateLimiter, RateLimitPolicy
from tools.security.sandbox import BASE_ENV_ALLOWLIST, Sandbox, SandboxError
from tools.security.secrets import Secret
from tools.security.validator import ValidatorError, guard, reject_dangerous
from tools.utils.helpers import mask_secret


# ==============================================================================
# AUTHORIZATION: A MALFORMED RULE MUST NOT BECOME A PERMISSIVE ONE
# ==============================================================================

def test_a_rule_without_a_permission_is_refused_at_load():
    """
    The bypass was one deleted line in a config file.

    `Rule` defaulted `permission` to `"*"`, `targets` to `()` and `allow` to
    True, and `matches` skipped both checks when they were empty. So a rule
    entry that lost its `permission` key -- a hand edit, a bad merge, a
    templating slip -- silently authorized everything.
    """
    with pytest.raises(ValueError, match="does not name a permission"):
        compile_rules([{}])

    with pytest.raises(ValueError, match="does not name a permission"):
        compile_rules([{"targets": ["wipe"], "allow": True}])


def test_a_rule_must_be_constructed_with_a_permission():
    with pytest.raises(TypeError):
        Rule()  # type: ignore[call-arg]

    with pytest.raises(ValueError):
        Rule(permission="   ")


def test_an_allow_rule_can_be_scoped_to_named_principals():
    """A rule used to ignore the principal entirely."""
    authorizer = Authorizer(rules=[requirement_rule("tool.read", principals=["svc:api"])])

    assert authorizer.may(principal="svc:api", permission="tool.read")
    assert not authorizer.may(principal="anonymous", permission="tool.read")
    assert not authorizer.may(principal="svc:api", permission="tool.write")


def test_a_deny_rule_wins_over_an_allow_rule_appended_after_it():
    """
    Under first-match-wins, appending an allow rule overrides an earlier deny
    and the resulting grant is invisible in the diff of the appended line.
    """
    authorizer = Authorizer(rules=[deny_rule("tool.read"), requirement_rule("tool.read")])
    assert not authorizer.may(principal="svc:api", permission="tool.read")

    reordered = Authorizer(rules=[requirement_rule("tool.read"), deny_rule("tool.read")])
    assert not reordered.may(principal="svc:api", permission="tool.read")


def test_an_authorizer_with_no_rules_denies():
    assert not Authorizer().may(principal="svc:api", permission="tool.read")


# ==============================================================================
# AUTHENTICATION: EXPIRY THAT NEVER RAN
# ==============================================================================

def test_token_expiry_is_computable():
    """
    `Token.expired` deferred `from .utils.helpers import now_utc`, and
    `tools.security.utils` does not exist. Every credential carrying an expiry
    raised ModuleNotFoundError on the one check meant to reject it.
    """
    assert Token(value="x", expires_at=1.0).expired is True
    assert Token(value="x", expires_at=None).expired is False


def test_an_expired_token_is_refused():
    principal = Principal(id="svc:api")
    authenticator = TokenAuthenticator(
        {"live": principal, "stale": principal},
        expiries={"stale": 1.0},
    )

    assert authenticator.authenticate({"token": "live"}) == principal

    with pytest.raises(AuthenticationError, match="expired"):
        authenticator.authenticate({"token": "stale"})

    with pytest.raises(AuthenticationError, match="unknown"):
        authenticator.authenticate({"token": "never-issued"})


# ==============================================================================
# ENCRYPTION: MALLEABILITY
# ==============================================================================

def test_a_tampered_ciphertext_is_refused_rather_than_decrypted():
    """
    The reproduction that motivated the rewrite: flip one ciphertext byte and
    the corresponding plaintext byte flips, with no error raised. `admin=0`
    became `admin=9` without the key.
    """
    sealed = encrypt_text("admin=0", "master")
    raw = bytearray(base64.b64decode(sealed))
    raw[20] ^= 0x09
    tampered = base64.b64encode(bytes(raw)).decode("ascii")

    with pytest.raises(IntegrityError):
        decrypt_text(tampered, "master")


def test_a_truncated_ciphertext_is_refused():
    sealed = encrypt_text("payload", "master")
    raw = base64.b64decode(sealed)

    with pytest.raises(IntegrityError):
        decrypt_text(base64.b64encode(raw[:-4]).decode("ascii"), "master")


def test_the_wrong_master_key_is_refused_not_returned_as_noise():
    sealed = encrypt_text("payload", "master")
    with pytest.raises(IntegrityError):
        decrypt_text(sealed, "different-master")


def test_a_roundtrip_survives_text_and_bytes():
    assert decrypt_text(encrypt_text("hello", "m"), "m") == "hello"
    assert decrypt_bytes(encrypt_bytes(bytes([255, 0]) + b"raw", "m"), "m") == (
        bytes([255, 0]) + b"raw"
    )


def test_identical_plaintexts_do_not_produce_identical_ciphertexts():
    assert encrypt_text("same", "m") != encrypt_text("same", "m")


def test_derive_key_is_deterministic_and_demands_a_salt():
    """
    `derive_key(master)` used to generate a random salt, use it, and discard
    it -- so the function returned a different key on every call and nothing
    encrypted under one call could be decrypted after another.
    """
    salt = b"0123456789abcdef"
    assert derive_key("master", salt=salt) == derive_key("master", salt=salt)
    assert derive_key("master", salt=salt) != derive_key("master", salt=b"different-salt!!")

    with pytest.raises(ValueError, match="salt"):
        derive_key("master", salt=b"")


def test_garbage_input_raises_integrity_error_not_a_decoding_error():
    with pytest.raises(IntegrityError):
        decrypt_text("not base64 at all !!", "m")


# ==============================================================================
# VALIDATOR: A GATEWAY THAT INSPECTED NOTHING
# ==============================================================================

@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "x UNION SELECT password FROM users",
        "javascript:fetch('//evil')",
        "'; DROP TABLE blocks; --",
    ],
)
def test_guard_inspects_field_values(payload: str):
    """
    `guard` passed the whole mapping to each rule. `reject_dangerous` opens
    with `isinstance(value, str)`, saw a dict, returned None -- so the "hard
    security gateway" passed every payload without one rule reading it.
    """
    with pytest.raises(ValidatorError):
        guard({"query": payload}, rules=[reject_dangerous])


def test_guard_still_passes_ordinary_input():
    guard({"chain": "ethereum", "block": "21000000"}, rules=[reject_dangerous])


def test_guard_names_the_field_that_failed():
    with pytest.raises(ValidatorError, match="query"):
        guard({"chain": "ethereum", "query": "<script>x</script>"}, rules=[reject_dangerous])


# ==============================================================================
# RATE LIMIT: THE RACE, AND THE UNBOUNDED MAP
# ==============================================================================

def test_the_limiter_holds_its_limit_under_concurrency():
    """
    `_prune` took the lock, released it, the caller compared lengths, then
    re-took the lock to append. Threads interleaving in that gap all saw
    room and all appended.
    """
    limit = 20
    limiter = RateLimiter(default_policy=RateLimitPolicy(limit=limit, window=60))
    admitted = []
    guard_lock = threading.Lock()

    def hammer() -> None:
        for _ in range(50):
            try:
                limiter.allow("rpc")
            except RateLimitError:
                continue
            with guard_lock:
                admitted.append(1)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(admitted) == limit


def test_the_window_map_is_bounded():
    """
    Names are caller-supplied, so an unbounded map is a memory-exhaustion
    path reachable by whoever chooses them.
    """
    limiter = RateLimiter(
        default_policy=RateLimitPolicy(limit=5, window=60), max_keys=100
    )
    for index in range(3000):
        limiter.allow(f"caller-chosen-{index}")

    assert limiter.tracked_keys() <= 100


def test_ordinary_limiting_still_works():
    limiter = RateLimiter(default_policy=RateLimitPolicy(limit=2, window=60))

    assert limiter.remaining("x") == 2
    limiter.allow("x")
    limiter.allow("x")
    assert limiter.remaining("x") == 0
    assert not limiter.can("x")

    with pytest.raises(RateLimitError):
        limiter.allow("x")

    limiter.reset("x")
    assert limiter.can("x")


# ==============================================================================
# PERMISSIONS
# ==============================================================================

def test_a_denial_is_not_an_oserror():
    """
    `class PermissionError(PermissionError)` inherited the builtin, which is
    an OSError. Any `except OSError:` around file or socket work -- and this
    agent reads databases and dials RPC endpoints -- swallowed the denial.
    """
    assert not issubclass(PermissionError, OSError)

    with pytest.raises(PermissionError):
        deny_all().check("anon", "tool.read")


def test_allow_all_allows():
    """It stored the grant under the key `"*"` and looked it up under the caller's id."""
    checker = allow_all()
    assert checker.may("svc:api", "anything.at.all")
    assert checker.may("user:someone", "other.permission")


def test_deny_all_still_denies_and_a_scoped_map_is_unaffected():
    assert not deny_all().may("svc:api", "anything")
    assert not PermissionChecker(grants={"svc:a": ["x"]}).may("svc:b", "x")


def test_decision_history_is_bounded():
    checker = PermissionChecker(grants={"svc:api": ["tool.*"]}, history=50)
    for _ in range(2000):
        checker.may("svc:api", "tool.read")

    assert len(checker.decisions) == 50


# ==============================================================================
# SECRETS
# ==============================================================================

def test_a_secret_refuses_to_be_pickled_or_copied():
    """
    `__slots__` does not stop pickling: the default `__reduce_ex__`
    serialises the slot values, writing `_value` out past every masking path
    the class provides.
    """
    secret = Secret("a-long-enough-credential", name="provider")

    with pytest.raises(TypeError):
        pickle.dumps(secret)
    with pytest.raises(TypeError):
        copy.deepcopy(secret)

    assert secret.raw == "a-long-enough-credential"


def test_a_secret_never_renders_in_plaintext():
    secret = Secret("a-long-enough-credential", name="provider")
    assert "a-long-enough-credential" not in str(secret)
    assert "a-long-enough-credential" not in repr(secret)


def test_the_mask_does_not_publish_the_secret_length():
    """`"*" * (len(value) - visible)` distinguished a 32-char key from a 64-char one."""
    short_key = "x" * 32
    long_key = "y" * 64

    assert len(mask_secret(short_key)) == len(mask_secret(long_key))


def test_a_short_secret_reveals_nothing():
    """Four visible characters out of seven is not a mask."""
    assert mask_secret("hunter2") == "[REDACTED]"


# ==============================================================================
# ISOLATION AND SANDBOX
# ==============================================================================

def test_a_policy_cannot_be_widened_after_it_is_trusted():
    import dataclasses

    policy = IsolationPolicy(file_roots=["/allowed"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.file_roots = ("/",)  # type: ignore[misc]

    assert policy.file_roots == ("/allowed",)


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",   # cloud instance metadata
        "metadata.google.internal",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
        "10.0.0.5",
        "192.168.1.1",
    ],
)
def test_an_open_network_policy_still_refuses_internal_hosts(host: str):
    """
    `block_hosts` defaulted to two spellings of loopback. The metadata
    endpoint is the highest-value SSRF target on a deployed host, and A01
    deploys to one.
    """
    assert not host_allowed(IsolationPolicy(allow_any_network=True), host)


def test_an_ordinary_host_is_still_reachable():
    assert host_allowed(IsolationPolicy(allow_any_network=True), "api.example.com")
    assert host_allowed(IsolationPolicy(hosts=["*.example.com"]), "rpc.example.com")
    assert not host_allowed(IsolationPolicy(hosts=["*.example.com"]), "rpc.evil.com")


def test_a_closed_policy_dials_nothing():
    assert not host_allowed(IsolationPolicy(), "api.example.com")


def test_the_child_environment_is_an_allowlist():
    """
    The deny-list dropped names containing "secret", "token", "key",
    "password" or "credential". `ALCHEMY_URL` and `DATABASE_URL` carry
    credentials inside the URL and match none of them.
    """
    for leaky in ("ALCHEMY_URL", "DATABASE_URL", "A01_RPC_ENDPOINT"):
        assert leaky not in BASE_ENV_ALLOWLIST

    assert "PATH" in BASE_ENV_ALLOWLIST
    # The parent's import path must not decide what the child executes.
    assert "PYTHONPATH" not in BASE_ENV_ALLOWLIST


def test_a_workdir_outside_the_policy_roots_is_refused(tmp_path):
    """
    The caller asked for a confinement and named a directory outside it.
    Honouring the second silently discards the first.
    """
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    sandbox = Sandbox(
        IsolationPolicy(file_roots=[str(allowed)]),
        workdir=str(outside),
    )
    with pytest.raises(SandboxError, match="file_roots"):
        sandbox.run("print(1)")


def test_a_workdir_inside_the_policy_roots_is_accepted(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()

    sandbox = Sandbox(IsolationPolicy(file_roots=[str(allowed)]), workdir=str(allowed))
    result = sandbox.run("print('ok')", timeout=60)

    assert result.ok, result.stderr
    assert result.stdout.strip() == "ok"
