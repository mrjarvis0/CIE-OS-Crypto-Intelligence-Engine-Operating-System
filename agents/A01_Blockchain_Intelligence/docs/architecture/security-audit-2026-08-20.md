# Security audit — `config/security` and `tools/security`

**Date:** 2026-08-20
**Scope:** 2,533 lines across `config/security/` (1,117) and `tools/security/` (1,416),
plus `tools/utils/helpers.py::mask_secret` and `tools/utils/paths.py`.
**Method:** read every line; reproduce each candidate finding against the shipped
code before writing it down; fix; add a regression test that fails on revert.

Sixteen defects. Eight were reproduced with a runnable script before the fix
landed; the rest are design faults where the code did what it said and what it
said was wrong. All sixteen are fixed. Regression tests live in
`tools/security/tests/test_hardening.py` (44 tests) and
`config/tests/test_security_hardening.py` (23 tests, 1 skipped on hosts that
forbid symlink creation).

The suite went from 1,466 passing to 1,679 passing with no failures.

---

## What these modules are, and what they are not

Neither package is a boundary the agent currently stands behind. A01 is
read-only, GET-only and loopback-bound; there is no untrusted caller reaching
`Authorizer`, and nothing in the running system calls `encrypt_text`.

That is the reason to fix them now rather than an argument against it. Every
one of these is a trap laid for the first person who wires one of these
modules to a real caller — and a security module that is wrong while unused
looks exactly like one that is right.

---

## Findings

Severity is about what the defect would cost the first time the module was
trusted, not about exposure today.

### 1. Arbitrary file read through the secrets API — critical

`config/security/secrets.py`

`SecretsManager._file_path` joined the caller's secret name onto
`secrets_dir`. `Path.__truediv__` places no constraint of its own, so a name
containing `..` walked out of the directory and an absolute name discarded it
entirely.

```
resolve("../../pyproject.toml")  ->  source='file:data\labels\..\..\pyproject.toml'
                                     2,220 bytes returned
```

Names reach this function from configuration files, CLI arguments and
provider identifiers. Fixed with a single-path-segment check — separators of
both platforms, `..`, NUL, drive letters and UNC roots — followed by a
containment re-check after `resolve()`, because the segment check cannot see
a symlink. A name that cannot be a filename now returns `None` for the file
source and may still resolve from the environment or an override, since
having no file is not an error.

### 2. The validator would not have caught it either — high

`config/security/validation.py`

`SECRET_NAME_PATTERN` was `^[A-Z0-9_][A-Z0-9_./-]{0,127}$`, which admits `/`
and `.`, so `A/../../.ENV` was a valid secret name. Nothing called
`validate_secret_name` from the resolution path, but a reader would
reasonably have concluded the names were being checked.

Pattern tightened to exclude the separator, with an explicit `..` rejection
on top. `.` and `-` stay: provider names use them and neither can escape a
directory alone.

### 3. Total authorization bypass from one missing config key — critical

`tools/security/authorization.py`

`Rule` defaulted `permission` to `"*"`, `targets` to `()` and `allow` to
`True`, and `Rule.matches` skipped both checks when they were empty. So
`Rule()` — and any rule dict that lost its `permission` key to a hand edit or
a bad merge — evaluated to *allow every permission, on every tool, for every
principal*:

```
compile_rules([{}])  ->  Rule(permission='*', targets=(), allow=True)
may(principal='anonymous', permission='security.admin.delete')  ->  True
```

The class docstring promised default-deny. A gate whose most likely typo is
total bypass is not a gate.

`permission` is now required with no default; `compile_rules` raises on an
entry that does not name one. Two further problems surfaced while fixing it:
rules ignored the principal entirely, so any allow-rule applied to every
identity including unauthenticated ones — `principals` now scopes a rule.
And evaluation was first-match-wins, under which appending an allow rule
silently overrides a deny placed earlier, with the grant invisible in the
diff of the appended line. Deny is now checked across the whole rule set
first.

### 4. Token expiry never ran — high

`tools/security/auth.py`

`Token.expired` deferred `from .utils.helpers import now_utc`.
`tools.security.utils` does not exist; `now_utc` lives at
`tools.utils.helpers`. Every credential carrying an expiry raised
`ModuleNotFoundError` on the one check meant to reject it.

```
Token(value='x', expires_at=1.0).expired
  -> ModuleNotFoundError: No module named 'tools.security.utils'
```

Worse, nothing consulted it in any case: `TokenAuthenticator` held a
`Mapping[str, Principal]`, so there was no expiry to consult. Import moved to
module scope; the authenticator now takes an `expiries` mapping and refuses
an expired token. Its lookup also became a constant-time comparison across
every entry, since a dict lookup returns sooner for an unknown token than a
known one.

### 5. Unauthenticated encryption — high

`tools/security/encryption.py`

A XOR keystream with no MAC. `hmac` was imported and never used. A stream
cipher without a tag is malleable: flip a ciphertext bit, flip exactly that
plaintext bit, with no key and no error on decryption.

```
encrypt_text("admin=0", "master")  ->  flip one byte  ->  decrypt_text(...)
  ->  'admin=9'          (no integrity error)
```

Rewritten as encrypt-then-MAC: PBKDF2 derives an encryption key and a
separate MAC key in one double-width call, the payload is masked with an
HMAC-SHA256 keystream, and the tag covers a version byte, the salt and the
ciphertext. `decrypt_text` verifies with `compare_digest` before producing a
single byte of plaintext. Tampering, truncation and a wrong master key all
raise `IntegrityError`. The module still says plainly that it is not a
reviewed AEAD.

### 6. A key-derivation function that returned a different key each call — high

`tools/security/encryption.py`

`derive_key(master)` defaulted `salt` to `os.urandom(16)` and then discarded
the salt. Two calls with the same master returned two different keys, so
anything encrypted under the first could not be decrypted after the second.

```
derive_key('m') == derive_key('m')  ->  False
```

`salt` is now required and raises when empty. A KDF that silently returns a
different answer each time is worse than one that refuses.

### 7. A security gateway that inspected nothing — high

`tools/security/validator.py`

`guard(data, rules=...)` passed the whole mapping to each rule. Rules are
written against field *values* — `reject_dangerous` opens with
`isinstance(value, str)` — so every rule received a `dict`, returned `None`,
and the "hard security gateway" passed everything:

```
guard({'q': '<script>alert(1)</script> DROP TABLE users'}, rules=[reject_dangerous])
  ->  passes
```

`guard` now applies each rule to each field and names the field that failed.
`validate_length` also stopped raising `TypeError` on a value with no length,
which a helper documented to return a message rather than throw should not do.

The pattern list gained `UNION SELECT`, `TRUNCATE` and `javascript:`, and a
comment stating what it is: a tripwire, **not** the defence against SQL
injection. That is parameterised queries, which is what
`database/repositories.py` uses throughout. A denylist presented as injection
defence is worse than none, because it invites someone to interpolate.

### 8. Rate limiter admitted more than its limit under concurrency — medium

`tools/security/rate_limit.py`

`_prune` took the lock, released it, the caller compared lengths, then
re-acquired the lock to append. Threads interleaving in that gap all saw room
and all appended. The class docstring said thread-safe.

Check and append now happen under a single acquisition. Verified: 8 threads ×
50 attempts against a limit of 20 admits exactly 20.

### 9. Unbounded window map — medium

`tools/security/rate_limit.py`

`_windows` grew one entry per distinct name, forever, and names come from
tool identifiers and scope strings the caller chooses. Bounded at 10,000 keys
with eviction of empty windows first, then the oldest. Verified: 5,000
distinct names against a cap of 100 leaves 100.

### 10. Sandbox environment scrubbing was a denylist — medium-high

`tools/security/sandbox.py`

The child inherited every variable whose name did not contain "secret",
"token", "key", "password" or "credential". That misses the shape secrets
take on this project entirely: `ALCHEMY_URL` and `DATABASE_URL` carry
credentials *inside the URL* and match none of those words.

Replaced with an allow-list of what a Python process needs to start.
`PYTHONPATH` is deliberately excluded — it would let the parent's import path
decide what the child executes. Verified: with `ALCHEMY_URL`, `DATABASE_URL`
and `A01_SECRET_X` set in the parent, the child sees 11 variables and none of
the three.

### 11. The sandbox documented a jail it did not build — medium-high

`tools/security/sandbox.py`

The module docstring said the child "receives read access to the allowed
roots via explicit arguments". No such argument was ever passed;
`IsolationPolicy.file_roots` reached the child not at all, and `cwd` is not a
jail. A reader who believed it would have handed untrusted code to a sandbox
that was not one.

Docstring rewritten to separate what is enforced (a time budget, a working
directory, an environment allow-list) from what is not (the child is an
ordinary OS process and can read any path and open any socket). An explicit
`workdir` outside the policy's roots is now refused rather than silently used.

### 12. SSRF to the cloud metadata endpoint — medium-high

`tools/security/isolation.py`

`block_hosts` defaulted to `["127.0.0.1", "localhost"]` — two spellings of
loopback and nothing else. `::1`, `0.0.0.0` and `169.254.169.254` all passed.
The last is the instance-metadata endpoint, the highest-value SSRF target on a
deployed host, and A01 deploys to one.

`restrict_ip` did block private ranges, but it was a separate function
nothing forced a caller to reach. `host_allowed` now applies it internally,
and the default deny-list covers loopback in every spelling plus the metadata
endpoints.

### 13. Security policy was mutable after being trusted — medium

`tools/security/isolation.py`

`IsolationPolicy` was a plain dataclass holding mutable lists. Anything
holding a reference could widen it after the decision to trust it was made,
and no reader could tell. Frozen, with sequence fields normalised to tuples.

### 14. Authorization denials were caught by `except OSError` — medium

`tools/security/permissions.py`

`class PermissionError(PermissionError)` inherited the builtin, which is an
`OSError` subclass. Any `except OSError:` around file or socket work — and
this agent reads SQLite databases and dials RPC endpoints — silently
swallowed a denial and carried on. Base changed to `Exception`; the exported
name is kept.

The unbounded `decisions` list on `PermissionChecker` was bounded to 1,000
entries in the same pass. A long-lived agent appends one per check.

### 15. `allow_all()` allowed nothing — medium

`tools/security/permissions.py`

It stored its grant under the literal key `"*"` and `PermissionMap.allows`
looked the grant up under the caller's own principal id, so it matched nobody:

```
allow_all().may('svc:api', 'anything')  ->  False
```

A helper whose name and behaviour are opposites is worse than no helper — the
failure surfaces as a denial somewhere unrelated. `allows` now honours a
`"*"` principal key. Deny-by-default is unchanged: a map without that key
grants nothing it was not given.

### 16. The secret mask published the secret's length — low-medium

`tools/utils/helpers.py`

`"*" * (len(value) - visible) + value[-visible:]` printed one asterisk per
hidden character, so every log line carrying a masked secret disclosed its
exact length — enough to distinguish a 32-character API key from a
64-character one. It also revealed four of seven characters of a short
secret. The mask is now fixed-width, and anything under twelve characters
renders as `[REDACTED]`.

Two smaller items fixed in the same pass: `tools.security.Secret` was
picklable and deep-copyable in plaintext despite `__slots__` — its hardened
sibling `config.security.SecretValue` already refused, and the two now agree —
and `ApiKeyManager.get_header` sent BASIC keys as a bare token rather than
`base64("user:pass")`, so every server rejected the header and the failure
surfaced as a provider auth error.

### Bonus: `ApiKeyManager()` could not be constructed — high

`config/security/api_keys.py`

The module imported `get_default_manager` from `.secrets` and then defined
its own function of the same name. The later definition won at call time, so
`ApiKeyManager.__init__` resolved its secrets backend to *itself* and recursed
until the stack ran out:

```
ApiKeyManager()  ->  RecursionError
```

The import is now aliased to `get_default_secrets_manager`. The package
`__init__` had already aliased both names for external callers, which is why
this went unnoticed — the collision existed only inside the module.

---

## Not fixed, and why

**`tools/utils/paths.py::is_relative_to(base, child)`** inverts the argument
order of `Path.is_relative_to(self, other)`. A caller writing the arguments
the standard-library way gets a silently wrong answer from a containment
check. It is used correctly at its two call sites, and renaming a public
helper is a change with its own blast radius — flagged rather than changed.

**Two secret abstractions.** `config.security.SecretValue` and
`tools.security.Secret` both wrap a credential with different hardening.
Merging them is the right end state and is a public-API change. The
`security/` redirect package now binds the two homes under distinct names
(`configuration` and `runtime`) specifically so a caller cannot reach for
`security.Secret` without seeing that there is a choice, and a test asserts
the surfaces stay unmerged.

**`restrict_ip` passes any hostname.** A hostname resolving to a private
address is not caught, because resolution happens later and elsewhere. This is
documented in the function rather than fixed: DNS rebinding needs a
resolve-then-pin transport, which is a different change.

---

## Verification

```bash
python -m pytest tools/security/tests/test_hardening.py config/tests/test_security_hardening.py -q
```

67 tests, 1 skipped where the host forbids symlink creation. Each names the
defect it guards and fails on a revert.

```bash
python -m pytest -q          # 1,679 passed, 1 skipped
python -m cli doctor         # 14/14 ok
```
