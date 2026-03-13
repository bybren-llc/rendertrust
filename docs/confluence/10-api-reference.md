# API Reference

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Base URL

| Environment | URL |
|-------------|-----|
| Production | `https://api.rendertrust.com` |
| Development | `http://localhost:8000` |

Interactive documentation available at `/docs` (Swagger UI) and `/redoc` (ReDoc).

---

## Authentication

Most endpoints require a JWT Bearer token in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

Node endpoints use a separate Node JWT with `token_type: "node"`.

---

## Endpoints

### Health & System

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | None | Liveness probe |
| GET | `/version` | None | App metadata (name, version, environment) |
| GET | `/metrics` | None | Prometheus metrics (text format) |
| GET | `/api/v1/health` | None | Liveness probe (alias) |
| GET | `/api/v1/health/ready` | None | Readiness probe (checks DB + Redis) |

#### GET /health

```json
// Response: 200
{ "status": "healthy" }
```

#### GET /api/v1/health/ready

```json
// Response: 200
{
  "status": "ready",        // or "degraded"
  "checks": {
    "database": "connected", // or "unavailable"
    "redis": "connected"     // or "unavailable"
  }
}
```

---

### Authentication

| Method | Path | Auth | Rate Limited |
|--------|------|------|-------------|
| POST | `/api/v1/auth/register` | None | Yes |
| POST | `/api/v1/auth/login` | None | Yes |
| POST | `/api/v1/auth/refresh` | Refresh Token | Yes |
| POST | `/api/v1/auth/logout` | Bearer | No |

#### POST /api/v1/auth/register

```json
// Request
{
  "email": "user@example.com",
  "name": "Jane Smith",
  "password": "securepassword123"   // min 8 characters
}

// Response: 201
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "name": "Jane Smith",
    "is_active": true
  },
  "tokens": {
    "access_token": "eyJhbGci...",
    "refresh_token": "eyJhbGci...",
    "token_type": "bearer"
  }
}

// Errors:
// 409 - Email already registered
// 422 - Validation error (bad email, short password)
```

#### POST /api/v1/auth/login

```json
// Request
{
  "email": "user@example.com",
  "password": "securepassword123"
}

// Response: 200
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "token_type": "bearer"
}

// Errors:
// 401 - Invalid credentials or inactive account
```

#### POST /api/v1/auth/refresh

```json
// Request
{ "refresh_token": "eyJhbGci..." }

// Response: 200
{
  "access_token": "eyJhbGci...",    // New token
  "refresh_token": "eyJhbGci...",   // New token (rotation)
  "token_type": "bearer"
}

// Errors:
// 401 - Invalid, expired, or wrong token type
```

#### POST /api/v1/auth/logout

```
Authorization: Bearer eyJhbGci...

// Response: 200
{ "message": "Logged out successfully" }
```

---

### Credits

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/credits/balance` | Bearer | Get current balance |
| GET | `/api/v1/credits/history` | Bearer | Transaction history |
| POST | `/api/v1/credits/deduct` | Bearer | Manual deduction |

#### GET /api/v1/credits/balance

```json
// Response: 200
{
  "balance": "1000.0000",
  "user_id": "550e8400-..."
}
```

#### GET /api/v1/credits/history

```
Query: ?limit=50&offset=0

// Response: 200
{
  "entries": [
    {
      "id": "uuid",
      "amount": "10.0000",
      "direction": "DEBIT",
      "source": "USAGE",
      "reference_id": "job-abc123",
      "balance_after": "990.0000",
      "description": "Job execution: render",
      "created_at": "2026-03-13T12:00:00Z"
    }
  ],
  "count": 42
}
```

#### POST /api/v1/credits/deduct

```json
// Request
{
  "amount": "10.0000",
  "reference_id": "manual-001",
  "description": "Manual adjustment"
}

// Response: 200 (ledger entry)
// Errors:
// 402 - Insufficient credits: { detail, available, requested }
// 422 - Invalid amount
```

---

### Jobs

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/jobs/dispatch` | Bearer | Submit and dispatch a job |
| GET | `/api/v1/jobs` | Bearer | List jobs |
| GET | `/api/v1/jobs/{job_id}` | Bearer | Get job details |
| POST | `/api/v1/jobs/{job_id}/cancel` | Bearer | Cancel a job |
| GET | `/api/v1/jobs/{job_id}/result` | Bearer | Get presigned download URL |

#### POST /api/v1/jobs/dispatch

```json
// Request
{
  "job_type": "render",
  "payload_ref": "s3://bucket/input/scene.blend"
}

// Response: 200
{
  "job_id": "uuid",
  "node_id": "uuid",
  "status": "DISPATCHED"
}

// Errors:
// 400 - No healthy nodes with matching capability
// 402 - Insufficient credits
```

#### GET /api/v1/jobs

```
Query: ?status=COMPLETED&limit=50&offset=0

// Response: 200
{
  "jobs": [
    {
      "id": "uuid",
      "node_id": "uuid",
      "job_type": "render",
      "payload_ref": "s3://...",
      "status": "COMPLETED",
      "result_ref": "s3://results/...",
      "error_message": null,
      "retry_count": 0,
      "queued_at": "2026-03-13T12:00:00Z",
      "dispatched_at": "2026-03-13T12:00:01Z",
      "completed_at": "2026-03-13T12:05:00Z",
      "created_at": "2026-03-13T12:00:00Z",
      "updated_at": "2026-03-13T12:05:00Z"
    }
  ],
  "count": 15
}
```

#### POST /api/v1/jobs/{job_id}/cancel

```json
// Response: 200 (updated job with new status)
// Errors:
// 400 - Job not in QUEUED or DISPATCHED state
// 404 - Job not found
```

#### GET /api/v1/jobs/{job_id}/result

```json
// Response: 200
{
  "job_id": "uuid",
  "download_url": "https://storage.example.com/bucket/key?X-Amz-Signature=...",
  "expires_in": 3600
}

// Errors:
// 404 - Job not found, not COMPLETED, or no result_ref
```

---

### Edge Nodes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/nodes/register` | None | Register new node |
| POST | `/api/v1/nodes/heartbeat` | Node JWT | Send heartbeat |
| WS | `/api/v1/relay/ws/{node_id}` | Query JWT | WebSocket relay |

#### POST /api/v1/nodes/register

```json
// Request
{
  "name": "gpu-node-east-1",
  "public_key": "-----BEGIN PUBLIC KEY-----\nMCow...",
  "capabilities": ["render", "inference"],
  "metadata": { "gpu": "RTX 4090" }
}

// Response: 201
{
  "node_id": "uuid",
  "challenge": "a1b2c3d4...64hexchars",
  "token": "eyJhbGci...",     // 24-hour JWT
  "status": "REGISTERED"
}
```

#### POST /api/v1/nodes/heartbeat

```json
// Request
Authorization: Bearer <node_jwt>
{
  "current_load": 0.45,
  "metadata": { "gpu_temp": 72 }
}

// Response: 200
{
  "node_id": "uuid",
  "status": "HEALTHY",
  "acknowledged": true
}
```

#### WS /api/v1/relay/ws/{node_id}

```
Connect: wss://api.rendertrust.com/api/v1/relay/ws/{node_id}?token=<jwt>

// Close codes:
// 4001 - Authentication failed
// 4002 - Heartbeat timeout (no pong in 90s)

// Gateway → Node messages:
{ "type": "job_dispatch", "job_id": "uuid", "job_type": "render", "payload_ref": "s3://..." }

// Node → Gateway messages:
{ "type": "job_status", "job_id": "uuid", "status": "running", "progress": 0.45 }
{ "type": "job_result", "job_id": "uuid", "status": "completed", "result_ref": "s3://..." }
```

---

### Webhooks

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/webhooks/stripe` | Stripe Signature | Stripe webhook receiver |

#### POST /api/v1/webhooks/stripe

```
Headers:
  stripe-signature: t=...,v1=...

Body: Raw Stripe event JSON

// Response: 200
{ "received": true }

// Errors:
// 400 - Missing signature or verification failure
```

---

### Ledger / Blockchain

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/ledger/{entry_id}/proof` | Bearer | Get Merkle proof |
| GET | `/api/v1/ledger/{entry_id}/verify` | Bearer | Verify on-chain |
| GET | `/api/v1/ledger/anchors` | Bearer | List anchor records |

#### GET /api/v1/ledger/{entry_id}/proof

```json
// Response: 200
{
  "entry_id": 42,
  "merkle_root": "a1b2c3d4...",
  "proof_hashes": ["e5f6a7b8...", "c9d0e1f2..."],
  "directions": ["left", "right"],
  "anchor_tx_hash": "0xabc...",
  "block_number": 12345
}
```

#### GET /api/v1/ledger/{entry_id}/verify

```json
// Response: 200
{
  "verified": true,
  "entry_id": 42,
  "merkle_root": "a1b2c3d4...",
  "on_chain_root": "a1b2c3d4...",
  "block_number": 12345,
  "tx_hash": "0xabc..."
}
```

#### GET /api/v1/ledger/anchors

```
Query: ?page=1&per_page=20&since=2026-03-01T00:00:00Z

// Response: 200
{
  "anchors": [...],
  "count": 5,
  "page": 1,
  "per_page": 20
}
```

---

## Error Response Format

All error responses follow this structure:

```json
{
  "detail": "Human-readable error message"
}
```

### Common HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request (invalid input) |
| 401 | Unauthorized (missing/invalid token) |
| 402 | Payment Required (insufficient credits) |
| 404 | Not Found |
| 409 | Conflict (duplicate resource) |
| 422 | Unprocessable Entity (validation error) |
| 429 | Too Many Requests (rate limited) |
| 500 | Internal Server Error |

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
