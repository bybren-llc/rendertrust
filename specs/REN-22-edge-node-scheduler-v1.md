<!-- Copyright 2026 ByBren, LLC. Licensed under the Apache License, Version 2.0. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# REN-22: Edge Node Scheduler v1

| Field            | Value                                      |
|------------------|--------------------------------------------|
| **Linear Ticket**| [REN-22](https://linear.app/cheddarfox/issue/REN-22) |
| **SAFe Type**    | Feature                                    |
| **Status**       | PLANNED                                    |
| **Priority**     | High                                       |
| **Story Points** | 13                                         |
| **PI / Sprint**  | Phase I / Sprint 3                         |

---

## Overview

Implement the v1 edge node scheduler for RenderTrust's trust fabric. The scheduler manages the lifecycle of distributed compute nodes: registration with cryptographic identity, heartbeat monitoring, health aggregation, and basic job dispatch via Redis queues. This is the control plane that enables RenderTrust to orchestrate any computational service across a distributed node fleet.

## User Story

As a **node operator**, I want to register my compute node with the RenderTrust network, so that my node can receive and execute computational jobs.

As a **platform operator**, I want real-time visibility into node health and availability, so that I can ensure reliable job dispatch and detect failures within seconds.

## Acceptance Criteria

- [ ] Nodes register via `POST /api/v1/nodes/register` with Ed25519 public key
- [ ] Registration returns a signed node token (JWT with node_id claim)
- [ ] Nodes send heartbeats via `POST /api/v1/nodes/heartbeat` every 30s
- [ ] Nodes missing 3 consecutive heartbeats are marked UNHEALTHY
- [ ] `GET /api/v1/nodes` returns paginated node list with status (HEALTHY, UNHEALTHY, OFFLINE)
- [ ] `GET /api/v1/nodes/{id}/health` returns node health summary (uptime, last heartbeat, load)
- [ ] Job dispatch pushes jobs to Redis queue keyed by node capability
- [ ] Scheduler selects least-loaded HEALTHY node for dispatch
- [ ] Node identity verified via challenge-response on registration
- [ ] All node-to-gateway communication is authenticated (node JWT)

## Technical Approach

### Architecture

```
                ┌─────────────────┐
                │   FastAPI GW    │
                │  core/scheduler │
                └───────┬─────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
   ┌────▼────┐    ┌─────▼─────┐   ┌────▼────┐
   │  Redis   │    │ PostgreSQL │   │ edgekit │
   │ Job Queue│    │ Node State │   │ Agents  │
   └─────────┘    └───────────┘   └─────────┘
```

### Data Model

```
EdgeNode
├── id: UUID (PK)
├── public_key: Text (Ed25519, PEM)
├── name: String
├── capabilities: JSONB (e.g., ["gpu-render", "cpu-inference"])
├── status: Enum(REGISTERED, HEALTHY, UNHEALTHY, OFFLINE)
├── last_heartbeat: DateTime (UTC)
├── current_load: Float (0.0 - 1.0)
├── metadata: JSONB (OS, GPU info, memory)
├── registered_at: DateTime (UTC)
└── updated_at: DateTime (UTC)

JobDispatch
├── id: UUID (PK)
├── node_id: UUID (FK → edge_nodes)
├── job_type: String
├── payload_ref: String (encrypted payload URI)
├── status: Enum(QUEUED, DISPATCHED, RUNNING, COMPLETED, FAILED)
├── queued_at: DateTime (UTC)
├── dispatched_at: DateTime (UTC, nullable)
└── completed_at: DateTime (UTC, nullable)
```

### API Endpoints

| Method | Path                        | Auth       | Purpose                    |
|--------|-----------------------------|------------|----------------------------|
| POST   | `/api/v1/nodes/register`    | API key    | Node registration          |
| POST   | `/api/v1/nodes/heartbeat`   | Node JWT   | Heartbeat + load report    |
| GET    | `/api/v1/nodes`             | JWT        | List nodes (admin)         |
| GET    | `/api/v1/nodes/{id}/health` | JWT        | Node health detail         |
| POST   | `/api/v1/jobs/dispatch`     | JWT+internal | Submit job for scheduling |

### Scheduler Algorithm (v1)

1. Filter nodes: status=HEALTHY, capabilities match job_type
2. Sort by current_load ascending
3. Select first node (least-loaded)
4. Push job to Redis queue: `queue:node:{node_id}`
5. Update JobDispatch status to DISPATCHED

### Key Decisions

- **#PATH_DECISION**: Redis queue over RabbitMQ for v1 (simpler ops, already in stack, sufficient for initial scale)
- **#PATH_DECISION**: Ed25519 over RSA for node identity (shorter keys, faster sign/verify, modern standard)
- **#PLAN_UNCERTAINTY**: Relay encryption protocol (`edgekit/relay/`) deferred to v2; v1 uses TLS transport only
- **#PLAN_UNCERTAINTY**: Auto-scaling and node pool management deferred to v2

### Patterns Referenced

- `patterns_library/api/webhook-handler.md` -- async event handling pattern
- `patterns_library/security/rate-limiting.md` -- heartbeat endpoint protection
- `patterns_library/config/environment-config.md` -- Redis connection config

## Dependencies

| Dependency             | Status     | Notes                            |
|------------------------|------------|----------------------------------|
| REN-61 (Core Platform) | Complete   | FastAPI, PostgreSQL, Redis       |
| REN-26 (CI/CD)         | Complete   | Quality gates for new code       |
| Auth system            | Complete   | `core/auth/` -- JWT middleware   |
| edgekit/poller/        | Exists     | Node-side polling agent          |
| edgekit/relay/         | Not started| Encrypted relay (deferred to v2) |

## Implementation Plan

1. Create `core/scheduler/models.py` -- EdgeNode + JobDispatch models
2. Create Alembic migration for scheduler tables
3. Create `core/scheduler/service.py` -- registration, heartbeat, dispatch logic
4. Create `core/scheduler/router.py` -- FastAPI endpoints
5. Implement heartbeat monitor background task (asyncio)
6. Implement Redis job queue producer
7. Integration tests with Redis test instance

## Testing Strategy

- **Unit**: Scheduler algorithm (node selection, load balancing)
- **Integration**: Registration flow, heartbeat lifecycle, job dispatch to Redis
- **Failure Modes**: Node goes offline mid-job, heartbeat timeout transitions
- **Load**: Simulate 50 nodes with concurrent heartbeats (locust)
- **Security**: Reject registration with invalid key, reject forged node JWT
- **Coverage Target**: 85%+ on `core/scheduler/`

## Security Considerations

- **OWASP A01 (Broken Access Control)**: Node endpoints require node JWT; admin endpoints require platform JWT with admin role
- **OWASP A02 (Cryptographic Failures)**: Ed25519 for node identity; challenge-response prevents key replay
- **OWASP A04 (Insecure Design)**: Heartbeat rate limiting prevents DoS; node status transitions are state-machine enforced
- **OWASP A07 (Security Misconfiguration)**: Redis requires AUTH; no default passwords
- **OWASP A08 (Software Integrity)**: Job payloads referenced by URI, verified by hash before execution
- **#EXPORT_CRITICAL**: Node private keys never transmitted to gateway; only public keys stored
- **#EXPORT_CRITICAL**: Job payloads encrypted at rest; decryption key held by node only
