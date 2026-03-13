# User Guide — Developer (SDK & API)

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Who Is This For?

This guide is for **developers** who want to integrate RenderTrust into their applications using the Python SDK or the REST API directly. This includes building automated pipelines, custom tooling, or integrating job submission into existing workflows.

---

## Python SDK

### Installation

```bash
pip install rendertrust
```

**Requirements**: Python 3.10+ | **Dependencies**: httpx >= 0.28.0

### Quick Start

```python
from rendertrust import RenderTrustClient

# Initialize client
client = RenderTrustClient(base_url="https://api.rendertrust.com")

# Authenticate
client.login("you@example.com", "your-password")

# Submit a job
result = client.submit_job(
    job_type="render",
    payload={"ref": "s3://my-bucket/scene.blend"}
)
print(f"Job ID: {result['job_id']}")
print(f"Node ID: {result['node_id']}")
print(f"Status: {result['status']}")

# Wait for completion (poll)
import time
while True:
    job = client.get_job(result["job_id"])
    if job["status"] in ("COMPLETED", "FAILED"):
        break
    time.sleep(5)

# Download result
if job["status"] == "COMPLETED":
    filepath = client.download_result(result["job_id"], "output.png")
    print(f"Result saved to: {filepath}")

# Clean up
client.close()
```

### Context Manager

```python
with RenderTrustClient(base_url="https://api.rendertrust.com") as client:
    client.login("you@example.com", "your-password")
    balance = client.get_balance()
    print(f"Credits: {balance['balance']}")
# Connection automatically closed
```

### Authentication Options

```python
# Option 1: Login with email/password
client = RenderTrustClient(base_url="https://api.rendertrust.com")
client.login("you@example.com", "your-password")

# Option 2: Pre-existing JWT token
client = RenderTrustClient(
    base_url="https://api.rendertrust.com",
    token="eyJhbGci..."
)

# Option 3: API key (for service accounts)
client = RenderTrustClient(
    base_url="https://api.rendertrust.com",
    api_key="rt_live_abc123..."
)
```

### Complete SDK Reference

#### `RenderTrustClient(base_url, api_key=None, token=None, timeout=30.0)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `base_url` | str | `https://api.rendertrust.com` | Gateway URL |
| `api_key` | str | None | API key (X-API-Key header) |
| `token` | str | None | Pre-existing JWT |
| `timeout` | float | 30.0 | Request timeout in seconds |

#### `client.login(email, password) -> dict`

Authenticates and stores tokens internally.

```python
result = client.login("user@example.com", "password")
# Returns: { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

#### `client.submit_job(job_type, payload, **kwargs) -> dict`

Dispatches a job to the network.

```python
result = client.submit_job(
    job_type="render",
    payload={"ref": "s3://bucket/input.blend"}
)
# Returns: { "job_id": "uuid", "node_id": "uuid", "status": "DISPATCHED" }
```

The `payload` dict:
- If `payload["ref"]` exists, uses it as `payload_ref`
- Otherwise, serializes the entire dict as JSON for `payload_ref`

#### `client.get_job(job_id) -> dict`

Gets full job details.

```python
job = client.get_job("uuid")
# Returns: { "id", "node_id", "job_type", "status", "result_ref", ... }
```

#### `client.list_jobs(status=None, limit=50) -> list[dict]`

Lists jobs with optional status filter.

```python
# All jobs
jobs = client.list_jobs()

# Only completed jobs
completed = client.list_jobs(status="COMPLETED")

# With limit
recent = client.list_jobs(limit=10)
```

#### `client.cancel_job(job_id) -> dict`

Cancels a QUEUED or DISPATCHED job.

```python
job = client.cancel_job("uuid")
```

#### `client.download_result(job_id, output_path=None) -> str`

Downloads the result file for a completed job.

```python
# Default filename: {job_id}.result
path = client.download_result("uuid")

# Custom filename
path = client.download_result("uuid", "my-render.png")

# Returns absolute path to saved file
print(f"Saved to: {path}")
```

#### `client.get_balance() -> dict`

Gets current credit balance.

```python
balance = client.get_balance()
print(f"Credits: {balance['balance']}")
```

#### `client.health() -> dict`

Checks gateway health.

```python
health = client.health()
# Returns: { "status": "healthy", "version": "0.1.0", "environment": "production" }
```

---

## Async SDK

For asyncio applications:

```python
import asyncio
from rendertrust import AsyncRenderTrustClient

async def main():
    async with AsyncRenderTrustClient(base_url="https://api.rendertrust.com") as client:
        await client.login("you@example.com", "password")

        # Submit multiple jobs concurrently
        tasks = [
            client.submit_job("render", {"ref": f"s3://bucket/scene-{i}.blend"})
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        for r in results:
            print(f"Job {r['job_id']} → {r['status']}")

asyncio.run(main())
```

All methods are identical to the sync client but async:

```python
await client.login(email, password)
await client.submit_job(job_type, payload)
await client.get_job(job_id)
await client.list_jobs(status, limit)
await client.cancel_job(job_id)
await client.download_result(job_id, output_path)
await client.get_balance()
await client.health()
```

---

## Error Handling

The SDK raises typed exceptions for different error conditions:

```python
from rendertrust import (
    RenderTrustClient,
    AuthenticationError,
    InsufficientCreditsError,
    NotFoundError,
    ValidationError,
    ServiceUnavailableError,
    RenderTrustError,
)

client = RenderTrustClient(base_url="https://api.rendertrust.com")

try:
    client.login("wrong@email.com", "bad-password")
except AuthenticationError as e:
    print(f"Login failed: {e.message}")  # "Invalid credentials"
    print(f"Status: {e.status_code}")    # 401

try:
    client.submit_job("render", {"ref": "s3://bucket/scene.blend"})
except InsufficientCreditsError as e:
    print(f"Need more credits: {e.message}")  # 402
except NotFoundError as e:
    print(f"Not found: {e.message}")           # 404
except ValidationError as e:
    print(f"Invalid input: {e.message}")       # 422
except ServiceUnavailableError as e:
    print(f"Service down: {e.message}")        # 503
except RenderTrustError as e:
    print(f"Other error: {e.message}")         # Any other status
```

### Exception Hierarchy

```
RenderTrustError (base)
├── AuthenticationError (401)
├── InsufficientCreditsError (402)
├── NotFoundError (404)
├── ValidationError (422)
└── ServiceUnavailableError (503)
```

All exceptions have:
- `message: str` — Human-readable error
- `status_code: int` — HTTP status code
- `response_body: dict` — Full response body

---

## Direct API Integration

If you're not using Python, integrate via the REST API directly.

### Authentication

```bash
# Register
curl -X POST https://api.rendertrust.com/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "name": "Dev User", "password": "securepass123"}'

# Login
curl -X POST https://api.rendertrust.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "dev@example.com", "password": "securepass123"}'
# Save the access_token from response

# Refresh token
curl -X POST https://api.rendertrust.com/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "eyJhbGci..."}'
```

### Job Workflow

```bash
# Check balance first
curl https://api.rendertrust.com/api/v1/credits/balance \
  -H "Authorization: Bearer $TOKEN"

# Submit job
curl -X POST https://api.rendertrust.com/api/v1/jobs/dispatch \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "render", "payload_ref": "s3://bucket/input.blend"}'
# Save job_id from response

# Poll for completion
curl https://api.rendertrust.com/api/v1/jobs/$JOB_ID \
  -H "Authorization: Bearer $TOKEN"

# Download result (when COMPLETED)
curl https://api.rendertrust.com/api/v1/jobs/$JOB_ID/result \
  -H "Authorization: Bearer $TOKEN"
# Use the download_url from response to download directly
```

### Webhook Integration (Advanced)

For real-time job status updates without polling, connect to the WebSocket relay:

```python
import websockets
import json

async def monitor_jobs(token, node_id):
    uri = f"wss://api.rendertrust.com/api/v1/relay/ws/{node_id}?token={token}"
    async with websockets.connect(uri) as ws:
        async for message in ws:
            data = json.loads(message)
            if data["type"] == "job_status":
                print(f"Job {data['job_id']}: {data['status']}")
```

---

## Best Practices

### 1. Use Context Managers

Always use `with` or `async with` to ensure connections are cleaned up:

```python
with RenderTrustClient(...) as client:
    # Your code here
# Connection closed automatically
```

### 2. Handle Token Refresh

The SDK doesn't auto-refresh tokens. For long-running scripts:

```python
import time

client = RenderTrustClient(base_url="...")
client.login("email", "password")

# Re-login if token expires (after ~30 minutes)
last_login = time.time()
REFRESH_INTERVAL = 25 * 60  # 25 minutes

def ensure_auth():
    if time.time() - last_login > REFRESH_INTERVAL:
        client.login("email", "password")
        last_login = time.time()
```

### 3. Implement Retry Logic

For production integrations, add retry logic:

```python
import time
from rendertrust import RenderTrustClient, ServiceUnavailableError

def submit_with_retry(client, job_type, payload, max_retries=3):
    for attempt in range(max_retries):
        try:
            return client.submit_job(job_type, payload)
        except ServiceUnavailableError:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise
```

### 4. Batch Processing

For multiple jobs, submit concurrently with the async client:

```python
import asyncio
from rendertrust import AsyncRenderTrustClient

async def batch_process(scenes):
    async with AsyncRenderTrustClient(base_url="...") as client:
        await client.login("email", "password")

        # Submit all jobs
        submit_tasks = [
            client.submit_job("render", {"ref": scene})
            for scene in scenes
        ]
        results = await asyncio.gather(*submit_tasks)
        job_ids = [r["job_id"] for r in results]

        # Poll until all complete
        while True:
            jobs = await asyncio.gather(*[
                client.get_job(jid) for jid in job_ids
            ])
            pending = [j for j in jobs if j["status"] not in ("COMPLETED", "FAILED")]
            if not pending:
                break
            await asyncio.sleep(5)

        # Download all results
        completed = [j for j in jobs if j["status"] == "COMPLETED"]
        downloads = await asyncio.gather(*[
            client.download_result(j["id"], f"output-{j['id'][:8]}.png")
            for j in completed
        ])
        return downloads
```

---

## OpenAPI Specification

The full OpenAPI 3.1 spec is available at:

- **Interactive**: `https://api.rendertrust.com/docs` (Swagger UI)
- **Alternative**: `https://api.rendertrust.com/redoc` (ReDoc)
- **Raw JSON**: `https://api.rendertrust.com/openapi.json`
- **Exported**: `docs/api/openapi.json` in the repository

Use the OpenAPI spec to generate clients in any language:

```bash
# Generate TypeScript client
npx openapi-generator-cli generate \
  -i https://api.rendertrust.com/openapi.json \
  -g typescript-fetch \
  -o generated/ts-client

# Generate Go client
openapi-generator generate \
  -i https://api.rendertrust.com/openapi.json \
  -g go \
  -o generated/go-client
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| `/api/v1/auth/*` | 20 requests/minute per IP |
| All other `/api/*` | 100 requests/minute per IP |

When rate limited, you'll receive `429 Too Many Requests`. Back off and retry.

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
