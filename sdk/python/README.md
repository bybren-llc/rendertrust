# RenderTrust Python SDK

Python client for the [RenderTrust](https://github.com/ByBren-LLC/rendertrust) API. Provides both synchronous and asynchronous interfaces for job submission, status tracking, result download, and credit management.

## Installation

```bash
pip install rendertrust
```

Or install from source:

```bash
cd sdk/python
pip install -e .
```

## Quick Start

### Synchronous Client

```python
from rendertrust import RenderTrustClient

client = RenderTrustClient(base_url="https://api.rendertrust.com")

# Authenticate
client.login("user@example.com", "password")

# Submit a job
job = client.submit_job("render", {"ref": "s3://bucket/scene.blend"})
print(f"Job dispatched: {job['job_id']}")

# Check job status
status = client.get_job(job["job_id"])
print(f"Status: {status['status']}")

# List all jobs
jobs = client.list_jobs(status="completed", limit=10)

# Download result
path = client.download_result(job["job_id"], output_path="./result.bin")

# Check credit balance
balance = client.get_balance()
print(f"Credits: {balance['balance']}")

# Health check (no auth required)
health = client.health()
print(f"API status: {health['status']}")
```

### Async Client

```python
import asyncio
from rendertrust import AsyncRenderTrustClient

async def main():
    async with AsyncRenderTrustClient(base_url="https://api.rendertrust.com") as client:
        await client.login("user@example.com", "password")

        job = await client.submit_job("render", {"ref": "s3://bucket/scene.blend"})
        status = await client.get_job(job["job_id"])
        print(f"Job {job['job_id']}: {status['status']}")

asyncio.run(main())
```

### API Key Authentication

For service accounts or edge nodes, use API key auth instead of login:

```python
client = RenderTrustClient(
    base_url="https://api.rendertrust.com",
    api_key="your-api-key-here",
)
jobs = client.list_jobs()
```

### Pre-existing Token

If you already have a JWT token:

```python
client = RenderTrustClient(
    base_url="https://api.rendertrust.com",
    token="eyJhbGciOi...",
)
```

## Error Handling

The SDK raises typed exceptions for different error conditions:

```python
from rendertrust import (
    RenderTrustError,          # Base exception (any API error)
    AuthenticationError,       # 401 - Invalid credentials
    InsufficientCreditsError,  # 402 - Not enough credits
    NotFoundError,             # 404 - Resource not found
    ValidationError,           # 422 - Invalid input
    ServiceUnavailableError,   # 503 - No healthy nodes
)

try:
    client.submit_job("render", {"ref": "s3://payload"})
except AuthenticationError:
    print("Please log in first")
except InsufficientCreditsError as e:
    print(f"Need more credits: {e.response_body}")
except ServiceUnavailableError:
    print("No nodes available, try again later")
except RenderTrustError as e:
    print(f"API error {e.status_code}: {e.message}")
```

## API Reference

### RenderTrustClient / AsyncRenderTrustClient

| Method | Description |
|---|---|
| `login(email, password)` | Authenticate and store tokens |
| `submit_job(job_type, payload)` | Dispatch a job to an edge node |
| `get_job(job_id)` | Get job details by ID |
| `list_jobs(status=None, limit=50)` | List jobs with optional filter |
| `cancel_job(job_id)` | Cancel a queued/dispatched job |
| `download_result(job_id, output_path=None)` | Download completed job result |
| `get_balance()` | Get current credit balance |
| `health()` | Check API health status |

## Development

```bash
cd sdk/python
pip install -e '.[dev]'
pytest tests/ -v
ruff check .
```

## License

MIT License -- see [LICENSE-MIT](../../LICENSE-MIT)
