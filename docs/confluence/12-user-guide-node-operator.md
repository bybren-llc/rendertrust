# User Guide — Node Operator

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Who Is This For?

This guide is for **node operators** — people who run edge compute nodes on the RenderTrust network. You contribute computing resources (CPU, GPU) and earn credits for completing jobs.

---

## Prerequisites

- **Hardware**: Any Linux, macOS, or Windows machine with Docker
- **Minimum**: 2 CPU cores, 4 GB RAM, 20 GB free disk
- **Recommended**: GPU (NVIDIA) for render/inference jobs, 8+ GB RAM
- **Network**: Stable internet connection, outbound HTTPS access
- **Software**: Docker Engine 24+ and Docker Compose v2

---

## Quick Start

### 1. Install Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
# Log out and back in

# Verify
docker --version
```

### 2. Register Your Node

```bash
# Clone the RenderTrust repository (or install the edgekit package)
git clone https://github.com/bybren-llc/rendertrust.git
cd rendertrust

# Register with the gateway
pip install -e '.[edge]'
edgekit register \
  --gateway-url https://api.rendertrust.com \
  --name "my-gpu-node" \
  --capabilities render,inference
```

This will:
- Generate an Ed25519 keypair (`~/.edgekit/private_key.pem`, `public_key.pem`)
- Register your node with the RenderTrust gateway
- Save your config to `~/.edgekit/config.json`
- Display your **node ID** and **JWT token**

### 3. Start Your Node

```bash
# Set your credentials
export NODE_JWT="eyJhbGci..."  # From registration output
export GATEWAY_URL="wss://api.rendertrust.com/api/v1"

# Start with Docker Compose
docker compose -f docker-compose.edge.yml up -d
```

### 4. Verify It's Running

```bash
# Check health
curl http://localhost:8081/health
# Expected: { "status": "healthy", "relay_connected": true }

# View logs
docker compose -f docker-compose.edge.yml logs -f
```

Your node is now connected to the RenderTrust network and will automatically receive jobs matching your capabilities.

---

## Understanding Node States

| State | Meaning | Receives Jobs? |
|-------|---------|---------------|
| **REGISTERED** | Just registered, waiting for first heartbeat | No |
| **HEALTHY** | Active and accepting jobs | Yes |
| **UNHEALTHY** | Too many failures or missed heartbeats | No |
| **OFFLINE** | Extended period without heartbeat | No |

### State Transitions

```
REGISTERED ──(heartbeat)──→ HEALTHY
HEALTHY ──(3 failures)──→ UNHEALTHY
UNHEALTHY ──(heartbeat)──→ HEALTHY
HEALTHY/UNHEALTHY ──(no heartbeat 5min)──→ OFFLINE
OFFLINE ──(heartbeat)──→ HEALTHY
```

Your node automatically sends heartbeats to maintain HEALTHY status. If the WebSocket connection drops, the relay client reconnects with exponential backoff (1s, 2s, 4s, ... up to 30s).

---

## Job Execution

### How Jobs Arrive

```
1. Gateway assigns job to your node (least-loaded algorithm)
2. Gateway sends job_dispatch message via WebSocket
3. Your node's Worker Executor receives the job
4. Executor selects the appropriate plugin based on job_type
5. Plugin executes the job with resource limits:
   - Timeout: 5 minutes (default)
   - Memory: 2 GB limit
   - CPU: 600 seconds limit
6. On success: result uploaded, status → COMPLETED
7. On failure: error reported, may be retried
```

### Supported Job Types

Your node supports job types based on installed plugins:

| Plugin | Job Type | Description |
|--------|----------|-------------|
| **Echo** | `echo` | Returns input payload (connectivity test) |
| **CPU Benchmark** | `cpu_benchmark` | Prime number sieve (performance test) |

You can register capabilities during node registration that match these (and custom) job types.

### Adding Custom Plugins

Create a new plugin file in `edgekit/workers/plugins/`:

```python
# edgekit/workers/plugins/my_renderer.py
from edgekit.workers.plugins.base import BaseWorkerPlugin, WorkerResult
import uuid

class BlenderRenderPlugin(BaseWorkerPlugin):
    job_type = "blender_render"

    async def execute(self, job_id: uuid.UUID, payload: dict) -> WorkerResult:
        try:
            scene_url = payload.get("scene_url")
            # Your rendering logic here...
            return WorkerResult(success=True, result_ref="s3://results/output.png")
        except Exception as e:
            return WorkerResult(success=False, error=str(e))
```

Then register it in `edgekit/entrypoint.py`:
```python
def build_plugins():
    return [EchoPlugin(), CpuBenchmarkPlugin(), BlenderRenderPlugin()]
```

Rebuild your Docker image and restart.

---

## Monitoring Your Node

### Health Check Endpoint

```bash
curl http://localhost:8081/health
```

Response:
```json
{
  "status": "healthy",
  "relay_connected": true,
  "uptime_seconds": 86400
}
```

### Docker Logs

```bash
# Follow real-time logs
docker compose -f docker-compose.edge.yml logs -f

# Last 100 lines
docker compose -f docker-compose.edge.yml logs --tail 100
```

### Key Log Messages

| Message | Meaning |
|---------|---------|
| `Connected to relay server` | WebSocket connected |
| `Received job_dispatch` | New job assigned |
| `Job completed` | Job finished successfully |
| `Job failed` | Job execution error |
| `Connection lost, reconnecting...` | WebSocket dropped, auto-reconnecting |
| `Heartbeat acknowledged` | Gateway confirmed node is alive |

---

## Earning Credits

Node operators earn credits for completed jobs:

| Job Type | Credits Earned |
|----------|---------------|
| Render | 10 per job |
| AI Inference | 5 per job |
| CPU Benchmark | 1 per job |
| Echo (test) | 0 per job |

Earnings are calculated monthly and tracked via the payout service. Payouts are processed based on your total completed jobs.

### Maximizing Earnings

1. **Keep your node online** — Higher uptime = more job assignments
2. **Register multiple capabilities** — Receive more job types
3. **Use powerful hardware** — Lower load = more capacity = more jobs
4. **Stable network** — Fewer disconnections = fewer missed jobs
5. **Monitor health** — Fix issues before they cause UNHEALTHY status

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GATEWAY_URL` | Yes | — | Gateway WebSocket URL |
| `NODE_JWT` | Yes | — | Your node's JWT token |
| `NODE_ID` | No | Auto | Node UUID (from registration) |
| `LOG_LEVEL` | No | INFO | DEBUG, INFO, WARNING, ERROR |
| `HEALTH_PORT` | No | 8081 | Health check HTTP port |

### Resource Limits (Docker)

Edit `docker-compose.edge.yml` to adjust:

```yaml
deploy:
  resources:
    limits:
      memory: 1G       # Increase for larger jobs
      cpus: "2.0"      # Increase for more parallelism
```

### Files

| Path | Purpose |
|------|---------|
| `~/.edgekit/private_key.pem` | Ed25519 private key (mode 0600) |
| `~/.edgekit/public_key.pem` | Ed25519 public key |
| `~/.edgekit/config.json` | Node configuration |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **"Connection refused"** | Check GATEWAY_URL is correct. Verify internet connectivity. |
| **"Authentication failed" (4001)** | JWT may be expired. Re-register: `edgekit register --force ...` |
| **"Heartbeat timeout" (4002)** | Network instability. Client will auto-reconnect. |
| **Node stuck as REGISTERED** | Send a heartbeat. Ensure relay client is running. |
| **Node status UNHEALTHY** | Too many job failures. Fix plugin errors, restart node. |
| **High memory usage** | Reduce Docker memory limit or check for memory leaks in plugins. |
| **Jobs timing out** | Default timeout is 5 minutes. Optimize your plugins or increase timeout. |

### Re-Registration

If your JWT expires or keys are lost:

```bash
edgekit register \
  --gateway-url https://api.rendertrust.com \
  --name "my-gpu-node" \
  --capabilities render,inference \
  --force
```

The `--force` flag overwrites existing keys and config.

---

## Community Leaderboard

Top node operators are featured on the public leaderboard at the Community Portal:

- **Ranked by**: Jobs completed, uptime percentage, total earnings
- **Badges**: Gold (1st), Silver (2nd), Bronze (3rd)
- **Updated**: Every 60 seconds

Visit: `https://community.rendertrust.com`

---

*Apache 2.0 License | Copyright (c) 2026 ByBren, LLC*
