# Authentication & Security

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Authentication Architecture

RenderTrust uses a **dual authentication model**:

1. **User JWT** — For human users (creators, admins) accessing the API and desktop app
2. **Node JWT** — For edge nodes authenticating via Ed25519 cryptographic identity

---

## User Authentication (JWT)

### Token Types

| Type | TTL | Purpose |
|------|-----|---------|
| **Access Token** | 30 minutes | Short-lived, used for API requests |
| **Refresh Token** | 7 days | Long-lived, used to obtain new access tokens |

### Token Payload

```json
{
  "sub": "user-uuid",
  "exp": 1709312400,
  "iat": 1709310600,
  "token_type": "access",
  "jti": "unique-token-id"
}
```

### Auth Flow

```
1. REGISTER
   POST /api/v1/auth/register
   → Creates user (bcrypt hashed password)
   → Returns access_token + refresh_token

2. LOGIN
   POST /api/v1/auth/login
   → Verifies email + password
   → Returns access_token + refresh_token

3. API REQUEST
   GET /api/v1/credits/balance
   Authorization: Bearer <access_token>
   → Verifies token signature, expiry, blacklist
   → Injects user into request context

4. TOKEN REFRESH
   POST /api/v1/auth/refresh
   → Validates refresh_token (rejects access tokens used as refresh)
   → Blacklists old refresh token
   → Returns new access_token + refresh_token (rotation)

5. LOGOUT
   POST /api/v1/auth/logout
   Authorization: Bearer <access_token>
   → Blacklists token JTI in Redis
```

### Token Blacklist (Redis)

- **Storage**: Redis `SETEX` with key `blacklist:{jti}` and TTL = remaining token lifetime
- **Check**: Every token verification checks `is_revoked(jti)` against Redis
- **Fail-open**: If Redis is unavailable, tokens are NOT blacklisted (availability over security for non-critical ops)

### Rate Limiting

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/api/v1/auth/register` | Configurable | Sliding window |
| `/api/v1/auth/login` | Configurable | Sliding window |
| `/api/v1/auth/refresh` | Configurable | Sliding window |

Rate limiting is Redis-backed with sliding window algorithm. Fail-open if Redis unavailable.

---

## Edge Node Authentication (Ed25519)

### Registration Flow

```
1. NODE GENERATES KEYPAIR
   Ed25519 private key → saved to ~/.edgekit/private_key.pem (mode 0600)
   Ed25519 public key  → sent to gateway

2. NODE REGISTERS
   POST /api/v1/nodes/register
   {
     "name": "my-node",
     "public_key": "-----BEGIN PUBLIC KEY-----\n...",
     "capabilities": ["render", "inference"]
   }
   → Gateway returns: { node_id, challenge, token, status }

3. NODE AUTHENTICATES
   Uses JWT (token) for all subsequent requests
   Token valid for 24 hours
   Token payload: { sub: node_id, token_type: "node", capabilities: [...] }

4. HEARTBEAT
   POST /api/v1/nodes/heartbeat
   Authorization: Bearer <node_jwt>
   { "current_load": 0.3 }
   → Transitions node to HEALTHY state
```

### Challenge-Response

The gateway issues a 64-character hex challenge during registration. The node must sign this challenge with its Ed25519 private key to prove key ownership.

---

## Security Layers

### Layer 1: Network (Cloudflare)

| Protection | Configuration |
|------------|--------------|
| **SSL/TLS** | Full (strict) mode, TLS 1.2 minimum, TLS 1.3 enabled |
| **HSTS** | 6 months, includeSubDomains, preload |
| **WAF Rules** | SQL injection, XSS, path traversal blocking |
| **Rate Limiting** | 100 req/min API, 20 req/min auth endpoints |
| **Bot Protection** | Bot Fight Mode + suspicious UA challenges |
| **DNS** | SPF `-all` + DMARC `p=reject` (no email spoofing) |
| **Tunnel** | Outbound-only (no inbound ports exposed on VPS) |

### WAF Custom Rules

| Priority | Rule | Action |
|----------|------|--------|
| 1 | Allow Stripe webhook IPs | Skip WAF + rate limit |
| 10 | API rate limit (100/min) | 429 Too Many Requests |
| 11 | Auth rate limit (20/min) | 429 Too Many Requests |
| 20 | SQL injection patterns | 403 Forbidden |
| 21 | XSS patterns | 403 Forbidden |
| 22 | Path traversal patterns | 403 Forbidden |
| 30 | Suspicious user agents | Challenge |

### Layer 2: Application

| Protection | Implementation |
|------------|---------------|
| **CORS** | Restricted to configured origins |
| **Security Headers** | OWASP recommended (nosniff, DENY, XSS, HSTS) |
| **Request ID** | X-Request-ID for distributed tracing |
| **Input Validation** | Pydantic v2 models on all endpoints |
| **Password Hashing** | bcrypt with salt |
| **Token Rotation** | Refresh tokens are single-use |
| **Idempotency** | UNIQUE constraints on reference_id for ledger entries |

### Layer 3: Data

| Protection | Implementation |
|------------|---------------|
| **Encryption at Rest** | AES-256-GCM for stored payloads |
| **Encryption in Transit** | TLS 1.2+ everywhere |
| **Object Storage Keys** | User-scoped paths (`{user_id}/{job_id}/result`) |
| **Key Validation** | No `..`, no leading `/`, no null bytes |
| **Database** | Non-negative balance CHECK constraint |
| **Secrets** | Pydantic SecretStr, production validator |

### Layer 4: Infrastructure

| Protection | Implementation |
|------------|---------------|
| **Container Security** | Non-root user, no-new-privileges, read-only rootfs |
| **Resource Limits** | CPU and memory limits on all containers |
| **Log Sanitization** | No PII or payment details in logs |
| **Dependency Scanning** | pip-audit in CI (weekly + per-PR) |
| **SAST** | Semgrep scanning auth, API, config, database modules |
| **Secret Scanning** | Gitleaks in CI |

---

## mTLS for Edge Nodes

Edge nodes use mutual TLS for WebSocket connections:

- **Internal CA** — Self-signed certificate authority for the RenderTrust network
- **Node Certificates** — Each node gets a unique certificate during registration
- **Gateway Verification** — Gateway validates node certificate chain
- **Node Verification** — Node validates gateway certificate (prevents MITM)

Configuration in `core/relay/tls.py` and `edgekit/relay/tls.py`.

---

## Security Incident Response

1. **Detection**: Prometheus alerts, Grafana dashboards, Cloudflare notifications
2. **Investigation**: Structured logs in Loki, correlated by request_id
3. **Mitigation**: Cloudflare WAF rule update, token blacklist, node status change
4. **Recovery**: Database backup restore, container restart, deploy rollback

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
