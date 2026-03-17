# Global Scheduler & Job Dispatch

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Overview

The scheduler manages the fleet of edge nodes and routes incoming jobs to the best available node using a **least-loaded dispatch algorithm**. It handles node registration, health monitoring, job queuing, and status transitions.

---

## Node Lifecycle

```
REGISTERED → HEALTHY → UNHEALTHY → OFFLINE
     │          ▲          │
     │          │          │
     └──────────┘          │
     (heartbeat)     (3 consecutive
                      failures or
                      heartbeat timeout)
```

### Node Statuses

| Status | Meaning | Can Receive Jobs? |
|--------|---------|-------------------|
| `REGISTERED` | Just registered, no heartbeat yet | No |
| `HEALTHY` | Active, heartbeating, accepting jobs | Yes |
| `UNHEALTHY` | Failed health checks or errors | No |
| `OFFLINE` | No heartbeat for extended period | No |

### Node Model

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `public_key` | String | Ed25519 PEM-encoded public key |
| `name` | String | Human-readable node name |
| `capabilities` | JSON | List of supported job types (e.g., `["render", "inference"]`) |
| `status` | Enum | REGISTERED, HEALTHY, UNHEALTHY, OFFLINE |
| `last_heartbeat` | DateTime | Last heartbeat timestamp |
| `current_load` | Float | 0.0 (idle) to 1.0 (full capacity) |
| `metadata` | JSON | Arbitrary node metadata (GPU info, location, etc.) |

---

## Job Lifecycle

```
QUEUED → DISPATCHED → RUNNING → COMPLETED
                  │          │
                  │          └→ FAILED → (retry) → QUEUED
                  │                        │
                  └→ CANCELLED             └→ DEAD LETTER
```

### Job Statuses

| Status | Meaning |
|--------|---------|
| `QUEUED` | Created, waiting for dispatch |
| `DISPATCHED` | Assigned to a node, in Redis queue |
| `RUNNING` | Node is actively executing the job |
| `COMPLETED` | Job finished successfully, result available |
| `FAILED` | Job execution failed |

### Job Model

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `node_id` | UUID (FK) | Assigned edge node |
| `job_type` | String | Job category (render, inference, etc.) |
| `payload_ref` | String | S3 URI, IPFS CID, or inline reference |
| `status` | Enum | Current job state |
| `result_ref` | String | S3 URI to job result (set on completion) |
| `error_message` | Text | Error details (set on failure) |
| `retry_count` | Integer | Number of retry attempts |
| `queued_at` | DateTime | When job was created |
| `dispatched_at` | DateTime | When job was assigned to node |
| `completed_at` | DateTime | When job finished (success or failure) |

---

## Dispatch Algorithm

The dispatch algorithm uses **least-loaded routing** among healthy nodes with matching capabilities:

```python
async def find_best_node(session, job_type) -> EdgeNode | None:
    # 1. Query nodes WHERE status = HEALTHY
    # 2. Filter by capability: job_type in node.capabilities
    # 3. Order by current_load ASC (least loaded first)
    # 4. Return first match (or None if no eligible nodes)
```

### Full Dispatch Flow

```
POST /api/v1/jobs/dispatch
{
  "job_type": "render",
  "payload_ref": "s3://bucket/input/scene.blend"
}

1. Authenticate user (JWT Bearer token)
2. Check sufficient credits for job_type
   → 402 if insufficient
3. Find best node (least-loaded with matching capability)
   → 400 if no eligible nodes
4. Create JobDispatch record (status=DISPATCHED)
5. Push to Redis queue: queue:node:{node_id}
   JSON: { job_id, job_type, payload_ref }
6. Return { job_id, node_id, status: "DISPATCHED" }
```

### Redis Queue Format

Each node has a dedicated Redis list: `queue:node:{node_id}`

```json
{
  "job_id": "uuid",
  "job_type": "render",
  "payload_ref": "s3://bucket/input/scene.blend"
}
```

The edge node's relay client polls this queue via the WebSocket relay server.

---

## Fleet Management

### Node Registration

```
POST /api/v1/nodes/register
{
  "name": "gpu-node-east-1",
  "public_key": "-----BEGIN PUBLIC KEY-----\nMCow...",
  "capabilities": ["render", "inference"],
  "metadata": {"gpu": "RTX 4090", "vram_gb": 24}
}

Response: 201 Created
{
  "node_id": "uuid",
  "challenge": "64-char-hex-string",
  "token": "eyJhbGci...",  // JWT valid 24 hours
  "status": "REGISTERED"
}
```

### Node Heartbeat

```
POST /api/v1/nodes/heartbeat
Authorization: Bearer <node_jwt>
{
  "current_load": 0.45,
  "metadata": {"gpu_temp": 72, "jobs_running": 2}
}

Response: 200 OK
{
  "node_id": "uuid",
  "status": "HEALTHY",
  "acknowledged": true
}
```

Effects:
- Updates `last_heartbeat` to current time
- Updates `current_load` and `metadata`
- Transitions `REGISTERED` or `UNHEALTHY` → `HEALTHY`

### Fleet Listing (Admin)

```
GET /api/v1/nodes
Authorization: Bearer <admin_jwt>

Response: 200 OK
{
  "nodes": [
    {
      "id": "uuid",
      "name": "gpu-node-east-1",
      "status": "HEALTHY",
      "current_load": 0.45,
      "capabilities": ["render", "inference"],
      "last_heartbeat": "2026-03-13T12:00:00Z"
    }
  ],
  "count": 5
}
```

---

## Error Handling & Retry

### Retry Policy

- **Max Retries**: 3 attempts with exponential backoff
- **Backoff**: 1s, 2s, 4s (configurable multiplier)
- **Retry Conditions**: Job status = FAILED and retry_count < max_retries

```python
# core/scheduler/retry.py
async def retry_failed_job(session, job):
    if job.retry_count >= MAX_RETRIES:
        await move_to_dead_letter(session, job)
        return

    job.retry_count += 1
    job.status = JobStatus.QUEUED
    # Re-dispatch with backoff delay
```

### Dead Letter Queue

Jobs that exhaust all retry attempts are moved to the dead letter queue:

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | UUID (FK) | Original job reference |
| `original_payload` | String | Original job payload |
| `error_history` | JSON | List of all error messages across retries |
| `failed_at` | DateTime | When moved to DLQ |
| `retry_count` | Integer | Total attempts made |

### Circuit Breaker

Protects the fleet from cascading failures:

```
3 consecutive failures from a node
    → Node status: HEALTHY → UNHEALTHY
    → Queued jobs redistributed to other nodes
    → Node must heartbeat again to recover
```

---

## Auto-Scale Trigger

```python
# core/scheduler/autoscale.py
# Monitors fleet utilization and emits scaling events

if average_load > 0.80:
    publish("scale:up", {"reason": "high_load", "current_avg": average_load})

if average_load < 0.20:
    publish("scale:down", {"reason": "low_load", "current_avg": average_load})
```

Events published to Redis pubsub channel `rendertrust:autoscale`.

---

*Apache 2.0 License | Copyright (c) 2026 ByBren, LLC*
