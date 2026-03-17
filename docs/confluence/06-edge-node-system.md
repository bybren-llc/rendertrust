# Edge Node System

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Overview

The Edge Node System (`edgekit/`) is the runtime that operators install on their machines to join the RenderTrust compute network. It connects to the gateway via WebSocket, receives jobs, executes them in isolated environments, uploads results, and reports status.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Edge Node (edgekit)               │
│                                                   │
│  ┌────────────┐   ┌──────────────┐   ┌────────┐ │
│  │ Relay      │   │ Worker       │   │ Health │ │
│  │ Client     │──▶│ Executor     │   │ Server │ │
│  │ (WebSocket)│   │              │   │ (:8081)│ │
│  └────────────┘   │ ┌──────────┐ │   └────────┘ │
│                    │ │ Plugins  │ │               │
│                    │ │ ┌──────┐ │ │               │
│                    │ │ │ Echo │ │ │               │
│                    │ │ ├──────┤ │ │               │
│                    │ │ │ CPU  │ │ │               │
│                    │ │ ├──────┤ │ │               │
│                    │ │ │Custom│ │ │               │
│                    │ │ └──────┘ │ │               │
│                    │ └──────────┘ │               │
│                    └──────────────┘               │
└─────────────────────────────────────────────────┘
         │
         │ WebSocket (wss://)
         ▼
┌─────────────────────┐
│  Gateway Relay      │
│  Server             │
└─────────────────────┘
```

---

## Node Registration

### Prerequisites

- Python 3.11+
- Docker (for containerized deployment)
- Network access to the RenderTrust gateway

### CLI Registration

```bash
# Install edgekit
pip install rendertrust[edge]

# Register with gateway
edgekit register \
  --gateway-url https://api.rendertrust.com \
  --name "my-gpu-node" \
  --capabilities gpu-render,cpu-inference
```

### What Happens

1. **Key Generation**: Creates Ed25519 keypair
   - Private key: `~/.edgekit/private_key.pem` (mode 0600)
   - Public key: `~/.edgekit/public_key.pem`

2. **Gateway Registration**: POSTs to `/api/v1/nodes/register`
   - Sends: name, public_key, capabilities
   - Receives: node_id, challenge, JWT token

3. **Config Saved**: `~/.edgekit/config.json`
   ```json
   {
     "node_id": "uuid",
     "name": "my-gpu-node",
     "gateway_url": "https://api.rendertrust.com",
     "jwt_token": "eyJhbGci...",
     "status": "REGISTERED",
     "capabilities": ["gpu-render", "cpu-inference"]
   }
   ```

### Re-registration

Use `--force` to overwrite existing keys:
```bash
edgekit register --gateway-url ... --name ... --force
```

---

## Relay Client

The relay client maintains a persistent WebSocket connection to the gateway.

### Connection

```
WebSocket URL: wss://api.rendertrust.com/api/v1/relay/ws/{node_id}?token={jwt}
```

### Features

- **Auto-reconnect**: Exponential backoff (1s → 2s → 4s → ... → 30s max)
- **Heartbeat**: Responds to gateway ping with pong
- **Job Assignment**: Receives `job_assign` messages from gateway
- **Status Reporting**: Sends `job_status` updates back to gateway

### Message Protocol

**Gateway → Node:**
```json
{
  "type": "job_dispatch",
  "job_id": "uuid",
  "job_type": "render",
  "payload_ref": "s3://bucket/input/scene.blend"
}
```

**Node → Gateway:**
```json
{
  "type": "job_status",
  "job_id": "uuid",
  "status": "running",
  "progress": 0.45,
  "detail": "Rendering frame 45/100"
}
```

```json
{
  "type": "job_result",
  "job_id": "uuid",
  "status": "completed",
  "result_ref": "s3://bucket/results/uuid/output.png"
}
```

---

## Worker Executor

The executor manages job execution with resource isolation and timeout enforcement.

### Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `timeout` | 300s (5 min) | Maximum execution time per job |
| `max_memory_bytes` | 2 GiB | Virtual memory limit |
| `max_cpu_seconds` | 600s | CPU time limit |

### Execution Flow

```
1. Job received from relay client
2. Look up plugin by job_type
3. Send status: RUNNING
4. Execute plugin with:
   - asyncio.wait_for(timeout)
   - RLIMIT_AS (memory limit)
   - RLIMIT_CPU (CPU time limit)
5. On success: Send status COMPLETED + result_ref
6. On failure: Send status FAILED + error detail
7. On timeout: Send status FAILED + "timeout exceeded"
```

### Resource Limits

Applied per job execution using `resource.setrlimit()`:
- `RLIMIT_AS` — Virtual address space (prevents memory bombs)
- `RLIMIT_CPU` — CPU time (prevents infinite loops)

---

## Worker Plugins

### Plugin Interface

```python
class BaseWorkerPlugin(ABC):
    job_type: str  # e.g., "echo", "cpu_benchmark", "render"

    @abstractmethod
    async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
        ...

@dataclass(frozen=True, slots=True)
class WorkerResult:
    success: bool
    result_ref: str | None = None  # S3 URI to output
    error: str | None = None       # Error message if failed
```

### Built-in Plugins

#### Echo Plugin (`job_type: "echo"`)

Returns the input payload as-is. Used for connectivity testing and validation.

```python
# Input payload: {"message": "hello"}
# Output result_ref: JSON string of the payload
```

#### CPU Benchmark Plugin (`job_type: "cpu_benchmark"`)

Runs a prime number sieve to benchmark CPU performance.

```python
# Input payload: {"limit": 100000}  (optional, default 100000, max 10000000)
# Output result_ref: JSON with { primes_found, limit, duration_seconds }
```

### Creating Custom Plugins

1. Create a new file in `edgekit/workers/plugins/`:

```python
from edgekit.workers.plugins.base import BaseWorkerPlugin, WorkerResult
import uuid

class MyRenderPlugin(BaseWorkerPlugin):
    job_type = "blender_render"

    async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
        try:
            scene_url = payload.get("scene_url")
            # Download scene, render, upload result...
            result_url = f"s3://results/{job_id}/output.png"
            return WorkerResult(success=True, result_ref=result_url)
        except Exception as e:
            return WorkerResult(success=False, error=str(e))
```

2. Register in `edgekit/entrypoint.py`:

```python
def build_plugins():
    return [EchoPlugin(), CpuBenchmarkPlugin(), MyRenderPlugin()]
```

---

## Docker Deployment

### Dockerfile (`edgekit/Dockerfile`)

Multi-stage build:
- **Builder**: Python 3.11-slim + gcc, installs `.[edge]` extras
- **Runtime**: Lean image with only runtime deps, non-root user `edgenode`

### Docker Compose (`docker-compose.edge.yml`)

```yaml
services:
  edge-node:
    build:
      context: .
      dockerfile: edgekit/Dockerfile
    environment:
      GATEWAY_URL: wss://api.rendertrust.com/api/v1
      NODE_JWT: ${NODE_JWT}
      NODE_ID: ${NODE_ID}      # Optional, auto-generated
      LOG_LEVEL: INFO
      HEALTH_PORT: 8081
    ports:
      - "8081:8081"           # Health check only
    volumes:
      - edge-data:/data
      - edge-config:/config
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: "2.0"
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### Running

```bash
# Set credentials
export NODE_JWT="eyJhbGci..."
export GATEWAY_URL="wss://api.rendertrust.com/api/v1"

# Start node
docker compose -f docker-compose.edge.yml up -d

# Check health
curl http://localhost:8081/health

# View logs
docker compose -f docker-compose.edge.yml logs -f
```

---

## Health Check Server

Runs on port 8081 (configurable via `HEALTH_PORT`):

```
GET /health
→ { "status": "healthy", "relay_connected": true, "uptime_seconds": 3600 }
```

Used by Docker health checks and monitoring systems.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GATEWAY_URL` | Yes | — | WebSocket URL to gateway |
| `NODE_JWT` | Yes | — | JWT auth token |
| `NODE_ID` | No | Auto-generated | Node UUID |
| `LOG_LEVEL` | No | INFO | Logging level |
| `HEALTH_PORT` | No | 8081 | Health check port |

---

*Apache 2.0 License | Copyright (c) 2026 ByBren, LLC*
