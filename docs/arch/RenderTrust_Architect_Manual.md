# RenderTrust – Architect Instruction Manual

_Oliver Insight IV • Rev 2 • May 2025_

---

## Table of Contents

1. **Core Vision & First Principles**
2. **High-Level System Anatomy**
3. **Control-Plane Components**
4. **Data-Plane & Edge Components**
5. **Security Architecture**
6. **Financial & Incentive Flows**
7. **CI/CD & Environments**
8. **Operational Playbooks**
9. **Disaster Recovery & Business Continuity**
10. **Future Roadmap & Sunset Criteria**

---

## 1. Core Vision & First Principles

1. **Creator Autonomy** – Every creative asset remains encrypted and under the originator's keys from ideation to final export.
2. **Edge-First Efficiency** – Off-load compute to the closest GPU/CPU, minimizing egress, latency, and carbon.
3. **Open Protocol Surface** – The A2A JSON-RPC spec is immutable; vendors can replace their stack without breaking interoperability.
4. **Incentive Alignment by Credits** – Single fungible token for spend & rewards reduces billing complexity and grows the compute network organically.

---

## 2. High-Level System Anatomy

### 2.1 Logical Layers

| Layer             | Function                                  | Primary Tech                    |
| ----------------- | ----------------------------------------- | ------------------------------- |
| **UX Layer**      | Desktop app, Fleet dashboard, Marketplace | Electron, React, Tailwind       |
| **Control Plane** | Scheduling, Identity, Billing             | FastAPI, Postgres, Stripe       |
| **Data Plane**    | Job storage, Audit ledger                 | Cloudflare R2, ERC-4337 roll-up |
| **Edge Plane**    | GPU/CPU workers, relays, tunnels          | Docker, Coolify agents          |
| **Observability** | Metrics, logs, traces                     | InfluxDB 3, Grafana 10, Loki    |

### 2.2 Traffic Flow (Latency budget ≤ 400 ms p95)

1. Creator submits encrypted job → Tunnel → Scheduler (**50 ms**)
2. Scheduler dispatch → Relay via Tunnel (**80 ms**)
3. Edge container runs job (**variable**)
4. Artefacts encrypted → back through Tunnel → Creator (**80 ms**)
5. Ledger & metrics fire async (**≤5 ms**)
   _Total control-plane round trip ≤215 ms; remainder is compute‐bound._

---

## 3. Control-Plane Components

### 3.1 Global Scheduler

- **Load Balancing Algo**: capability filter → latency score → earnings weight (Pareto front).
- **Error Handling**: if job fails twice on different nodes → escalate to cloud overflow queue.
- **Autoscaling**: KEDA watches Postgres `pending_jobs` table; scales 1→10 pods.

### 3.2 Credit Ledger

- **Schema**: `accounts`, `ledger_entries`, `usage_events`.
- **Atomicity**: DB transaction wraps job dispatch + creator debit to avoid credit overdraft.
- **Export**: nightly dump to Parquet in R2 for BI; GDPR erase via account ID filter.

### 3.3 Billing Service

- Listens to Stripe `checkout.session.completed` events.
- Map Price ID → credits via ENV.
- Idempotency by session ID.

---

## 4. Data-Plane & Edge Components

### 4.1 Edge Relay

- **Startup**: pulls latest `relay` image, verifies SHA-256 checklist pinned in Blueprint.
- **Security**: mutual-TLS to Cloudflare tunnel OR direct WireGuard if on-prem.
- **Sandbox**: Docker rootless + seccomp; upcoming migration to Firecracker once cgroup v2 support stabilizes.

### 4.2 Workload Containers

| Job Type             | Base Image                              | GPU RAM     | ETA Example      |
| -------------------- | --------------------------------------- | ----------- | ---------------- |
| Storyboard (SD-XL)   | `cheddarfox/rendertrust-comfyui:cu12.1` | 12 GB       | 4 s / frame      |
| LLM (Ollama Mixtral) | `ollama/ollama:0.1`                     | 0 / CPU opt | 80 tokens/s      |
| Voice (OpenVoice)    | `cheddarfox/rendertrust-voice:onnx`     | 6 GB        | 30 s / 10 s clip |

### 4.3 Node Poller

- Collects GPU mem/temp/util + container count.
- Pushes Influx line protocol via UDP to reduce overhead (<1 KB).
- Node offline if heartbeat >90 s.

---

## 5. Security Architecture

| Threat                        | Control                                       | Residual Risk                     |
| ----------------------------- | --------------------------------------------- | --------------------------------- |
| Rogue node exfiltrates script | AES-GCM encryption + audit hash               | Low (must break AES)              |
| JWT stolen                    | 24 h TTL, device fingerprint, revocation list | Very Low                          |
| Supply-chain attack           | Image digest pin + Trivy scan in CI           | Low                               |
| Edge container escape         | Rootless Docker + seccomp                     | Medium (will move to Firecracker) |

Pen-tests scheduled each quarter; last report (04-2025) zero critical findings.

---

## 6. Financial & Incentive Flows

```
graph LR
Creator -- credits--> Ledger
Ledger -- payout--> NodeOwner
ModuleDev -- usageEvent--> Ledger
Ledger -- revShare--> WTFB
```

- Credits priced at $0.10 per unit (100 units per $10 pack).
- Node earnings: 0.04 USD/GPU-min (≈0.4 credits).
- Module Dev: 85% after $1k lifetime.

---

## 7. CI/CD & Environments

- **Branches**: `main`, `dev`, `hotfix/*`.
- **Stages**:
  - **Dev Sandbox** – `dev` auto-deploy, mock GPUs.
  - **Staging** – PR merge to `main` with `-rc` tag.
  - **Prod** – Semantic tag `vX.Y.Z`; requires green smoke + manual approval.
- **Secrets**: pulled from Vault Agent sidecar at runtime.

---

## 8. Operational Playbooks

### 8.1 Add GPU Node (manual)

1. SSH into host, install drivers.
2. `curl -sL <installer>`; supply node token.
3. Verify in Fleet tab → run `nvidia-smi` remotely.

### 8.2 Hot Patch Module

1. Dev bumps Docker tag → pushes.
2. CI exports new manifest via `rendertrust-cli export`.
3. Scheduler rolls out after 1 successful canary job.

---

## 9. Disaster Recovery

| Asset    | Backup                 | RPO    | Restore                                |
| -------- | ---------------------- | ------ | -------------------------------------- |
| Postgres | WAL + nightly snapshot | 15 min | Ansible script `pg-restore.yml`        |
| S3 Jobs  | R2 CRR to EU           | 1 h    | Point app to secondary bucket          |
| Vault    | Raft snapshots hourly  | 1 h    | `vault operator raft snapshot restore` |

DR drill every 6 months.

---

## 10. Future Roadmap & Sunset Criteria

- **v2.0** – Firecracker micro-VM runtime, Stark-based ledger, <50 ms dispatch.
- **Sunset** – deprecate Docker rootful mode once all nodes upgraded.
- **Decommission path** for unused modules after 90 days zero calls.

---

### Contact Matrix

- **Arch-Decisions** – `#arch-sync`, Oliver Insight IV
- **Security** – `security@rendertrust.com`
- **Support** – [scott@wordstofilmby.com](mailto:scott@wordstofilmby.com)
- **Ops Runbook** – [https://runbooks.rendertrust.com](https://runbooks.rendertrust.com)
- **Sponsor** – [Words To Film By](https://www.wordstofilmby.com)

_—— End of Architect Manual ——_
