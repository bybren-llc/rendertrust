<!-- Copyright 2026 ByBren, LLC. SPDX-License-Identifier: MIT -->
# JWT Library Standardization Spike

**Date**: 2026-03-09
**Author**: Backend Developer Agent
**Time-box**: 1 hour
**Status**: Complete
**Linear**: REN-64

---

## 1. Problem Statement

The RenderTrust codebase uses two different JWT libraries: `python-jose` (declared in
`pyproject.toml`) and `PyJWT` (imported as `jwt` in edge/vault modules). This creates:

- **Dependency confusion**: `pyproject.toml` declares `python-jose[cryptography]` but two
  modules import `jwt` (the PyJWT namespace). Both packages can coexist, but `import jwt`
  resolves to whichever is installed -- if both are present, they conflict on the `jwt`
  module namespace.
- **Security surface**: Two libraries means two sets of CVEs to track, two upgrade cycles,
  and two sets of default behaviors (e.g., algorithm validation).
- **Maintenance burden**: Contributors must know which library a given file uses and follow
  different API conventions for each.

## 2. Current State Analysis

### 2.1 python-jose (declared dependency — actively used)

**Declared in**: `pyproject.toml` line 29 -- `"python-jose[cryptography]>=3.3.0,<4.0"`

**Mypy config**: `pyproject.toml` line 141 lists `jose.*` in `ignore_missing_imports`,
confirming this is the intended standard library.

**Active usage in core auth** (added in REN-61):

- **`core/auth/jwt.py`** (line 28): `from jose import JWTError, jwt` — primary JWT
  implementation (170+ LOC). Handles access/refresh token creation, verification,
  and the `get_current_user` FastAPI dependency. Uses `jwt.encode()`, `jwt.decode()`,
  and `JWTError` exception handling.
- **`core/auth/middleware.py`** (line 24): `from jose import JWTError` — auth middleware
  for additional JWT verification.

python-jose is the **actively used standard** for the core auth system. ADR-001
Section 6 established python-jose as the project standard, citing JWE support for
edge node token encryption.

**python-jose API surface**:
```python
from jose import jwt, JWTError
token = jwt.encode({"sub": "user"}, secret, algorithm="HS256")
payload = jwt.decode(token, secret, algorithms=["HS256"])
# JWE support via jose.jwe
```

### 2.2 PyJWT usage (core/ledger/vault/token_rotator.py)

**File**: `core/ledger/vault/token_rotator.py`
**Import**: `import jwt` (line 1, alongside `hvac`, `os`, `datetime`)
**Features used**:
- `jwt.encode()` -- creates HS256 token with `sub`, `iat`, `exp` claims (line 10-13)
- Algorithm: `HS256` only
- No decode, no JWE, no error handling for JWT-specific exceptions

```python
token = jwt.encode({"sub": node_id,
                    "iat": datetime.datetime.utcnow(),
                    "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24)},
                   JWT_SECRET, algorithm="HS256")
```

### 2.3 PyJWT usage (edgekit/poller/core/fleet_gateway.py)

**File**: `edgekit/poller/core/fleet_gateway.py`
**Import**: `import jwt` (line 3, alongside `os`, `datetime`)
**Features used**:
- `jwt.decode()` -- verifies HS256 token, extracts `sub` claim (line 13)
- `jwt.encode()` -- not used directly but the counterpart (`token_rotator.py`) creates
  tokens this module consumes
- Algorithm: `HS256` only
- Error handling: bare `except Exception` (line 14) -- not using `jwt.exceptions.DecodeError`

```python
def auth_check(tok):
    try:
        return jwt.decode(tok.split()[1], SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401)
```

### 2.4 Vault HCL Configuration

**File**: `core/ledger/vault/terraform/vault.hcl`
- Configures `vault_jwt_auth_backend_role` for edge nodes (lines 13-18)
- This is Vault's built-in JWT auth method -- it does not depend on either Python library
- Audience: `wtfb-edge`, claim: `sub`

### 2.5 pyproject.toml Dependency Declaration

- **Declared**: `python-jose[cryptography]>=3.3.0,<4.0` (in main `[project.dependencies]`)
- **Not declared**: `PyJWT` is not listed anywhere in `pyproject.toml`
- **Edge optional deps**: `hvac` is in `[project.optional-dependencies.edge]` but `PyJWT`
  is not, meaning the edge modules have an undeclared transitive dependency (likely pulled
  in by `hvac` which depends on `requests` but not `PyJWT`)

This is a correctness issue: the edge modules depend on PyJWT but it is not declared as a
dependency. It may work by accident if another package pulls it in transitively, but this
is fragile.

## 3. Library Comparison

| Feature | python-jose | PyJWT |
|---------|-------------|-------|
| PyPI package | `python-jose` | `PyJWT` |
| Import name | `jose` / `jose.jwt` | `jwt` |
| JWS (sign/verify) | Yes | Yes |
| JWE (encrypt/decrypt) | Yes | No (requires `PyJWE` or manual) |
| JWK support | Yes | Yes (v2.0+) |
| Algorithm support | RS256, HS256, ES256, PS256, EdDSA | RS256, HS256, ES256, PS256, EdDSA, OKP |
| Maintenance status | Low activity (last release: 2024-01) | Very active (regular releases) |
| PyPI downloads/month | ~8M | ~130M |
| Python 3.11+ support | Yes | Yes |
| Cryptography backend | Optional (`[cryptography]`) | Built-in (`cryptography` required) |
| API style | Mirrors `jose` JS library | Pythonic, class-based (`PyJWT` 2.x) |
| Namespace conflict risk | None (`jose.*`) | Yes -- conflicts with `python-jose` if both installed |

### 3.1 Maintenance Concern for python-jose

`python-jose` has significantly lower community activity compared to `PyJWT`. The package
has not seen a release since early 2024. However, JWT is a stable specification (RFC 7519)
and the library's feature set is mature. The `[cryptography]` backend delegates actual
crypto operations to the well-maintained `cryptography` package.

### 3.2 Namespace Conflict

Both `python-jose` and `PyJWT` install modules that can be imported as `jwt`. Specifically:
- `python-jose` installs `jose/` and a compatibility `jwt` shim in some configurations
- `PyJWT` installs `jwt/`

If both are installed, `import jwt` behavior is undefined and depends on installation order.
This is the most critical issue to resolve.

## 4. Recommendation

**STANDARDIZE on `python-jose`** and migrate all `import jwt` (PyJWT) usage.

### Rationale

1. **Already declared and actively used**: `python-jose[cryptography]` is the declared
   dependency and is actively used in `core/auth/jwt.py` and `core/auth/middleware.py`.
   PyJWT is undeclared and used only in legacy edge modules.
2. **JWE support**: RenderTrust's trust envelope architecture may require JWE for encrypted
   tokens in edge node communication. Only python-jose provides this natively.
3. **Consistency**: The mypy configuration already accounts for `jose.*` imports.
4. **Namespace safety**: Using `from jose import jwt` avoids the `import jwt` namespace
   collision entirely.
5. **Minimal migration**: Only two files need changes, and both use simple `encode`/`decode`
   operations that have direct equivalents in python-jose.

### Alternative Considered: Standardize on PyJWT

PyJWT is more actively maintained and has vastly higher adoption. However:
- It would require removing `python-jose` from `pyproject.toml` and adding `PyJWT`
- It would require updating the mypy `ignore_missing_imports` from `jose.*` to `jwt.*`
- It does not provide JWE, which the architecture may need
- It would be a reversal of the existing project decision

If JWE is definitively not needed, a future ADR could revisit this decision in favor of
PyJWT. For now, aligning with the existing declared dependency is the lowest-risk path.

## 5. Migration Plan

### 5.1 Changes to `core/ledger/vault/token_rotator.py`

**Current** (PyJWT):
```python
import hvac, jwt, os, datetime

JWT_SECRET = os.environ["JWT_SIGNING_KEY"]
token = jwt.encode({"sub": node_id, ...}, JWT_SECRET, algorithm="HS256")
```

**Migrated** (python-jose):
```python
import hvac
import os
import datetime
from jose import jwt

JWT_SECRET = os.environ["JWT_SIGNING_KEY"]
token = jwt.encode({"sub": node_id, ...}, JWT_SECRET, algorithm="HS256")
```

The `jose.jwt.encode()` API is identical to PyJWT's `jwt.encode()` for this use case.
Only the import line changes.

### 5.2 Changes to `edgekit/poller/core/fleet_gateway.py`

**Current** (PyJWT):
```python
import jwt, os, datetime

def auth_check(tok):
    try:
        return jwt.decode(tok.split()[1], SECRET, algorithms=["HS256"])["sub"]
    except Exception:
        raise HTTPException(status_code=401)
```

**Migrated** (python-jose):
```python
import os
import datetime
from jose import jwt, JWTError

def auth_check(tok):
    try:
        return jwt.decode(tok.split()[1], SECRET, algorithms=["HS256"])["sub"]
    except JWTError:
        raise HTTPException(status_code=401)
```

Changes:
1. Replace `import jwt` with `from jose import jwt, JWTError`
2. Replace bare `except Exception` with `except JWTError` for precise error handling
3. The `jwt.decode()` API is identical between the two libraries for this use case

### 5.3 Dependency Cleanup

No changes to `pyproject.toml` are needed -- `python-jose[cryptography]` is already
declared. However, verify that `PyJWT` is not installed in the development environment:

```bash
pip list | grep -i jwt
# Should show python-jose, should NOT show PyJWT
# If PyJWT is present: pip uninstall PyJWT
```

### 5.4 Additional Improvements (Out of Scope for Migration)

These issues exist in the current code and should be addressed in separate tickets:

1. **`token_rotator.py`**: Uses `datetime.datetime.utcnow()` which is deprecated in
   Python 3.12+. Should migrate to `datetime.datetime.now(datetime.UTC)`.
2. **`token_rotator.py`**: No input validation on `node_id` parameter.
3. **`fleet_gateway.py`**: Bare `except Exception` should become `except JWTError`
   (addressed in migration).
4. **`fleet_gateway.py`**: Missing import for `HTTPException` from FastAPI.
5. **Both files**: No type annotations (mypy is configured to ignore these modules).
6. **`fleet_gateway.py`**: Secret default `"changeme"` is a security risk in production.

### 5.5 Testing Strategy

1. Unit test: Verify token round-trip (encode in `token_rotator`, decode in
   `fleet_gateway`) produces identical results with python-jose as with PyJWT
2. Integration test: Verify Vault token rotation flow still works end-to-end
3. Verify no `import jwt` statements remain (except `from jose import jwt`)

```bash
# After migration, verify no direct PyJWT imports remain
grep -rn "^import jwt" core/ edgekit/
# Should return zero results

grep -rn "from jose import" core/ edgekit/
# Should show the migrated imports
```

## 6. Decision

**STANDARDIZE on `python-jose[cryptography]`.** Migrate `token_rotator.py` and
`fleet_gateway.py` to use `from jose import jwt` in a follow-up implementation ticket.

**Estimated effort**: 1 story point (simple import changes, no logic changes).

**Follow-up ticket**: Create REN-66 (or similar) to execute the migration described in
Section 5.

---

**References**:

- python-jose: https://github.com/mpdavis/python-jose
- PyJWT: https://github.com/jpadilla/pyjwt
- RFC 7519 (JWT): https://datatracker.ietf.org/doc/html/rfc7519
- RFC 7516 (JWE): https://datatracker.ietf.org/doc/html/rfc7516
- RenderTrust `pyproject.toml`: declares `python-jose[cryptography]>=3.3.0,<4.0`
