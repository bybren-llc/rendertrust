# RenderTrust Implementation Guide

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)

This directory is licensed under the MIT License. See `../../LICENSE-MIT`.

This guide provides comprehensive instructions for implementing and deploying the RenderTrust platform.

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [Edge Components](#edge-components)
5. [Deployment](#deployment)
6. [Security](#security)
7. [Monitoring](#monitoring)
8. [Disaster Recovery](#disaster-recovery)

## Overview

RenderTrust is a distributed Edge-AI Fabric that enables efficient workload distribution across edge devices and cloud resources. The platform consists of several key components:

- **Core Services**: Scheduler, Ledger, Billing, Gateway
- **Edge Kit**: Blueprints, Relay, Workers, Poller
- **SDK**: Client libraries and integration tools
- **Rollup Anchor**: Blockchain-based verification

## Architecture

The system follows a layered architecture:

1. **UX Layer**: Desktop app, Fleet dashboard, Marketplace (Electron, React, Tailwind)
2. **Control Plane**: Scheduling, Identity, Billing (FastAPI, Postgres, Stripe)
3. **Data Plane**: Job storage, Audit ledger (Cloudflare R2, ERC-4337 roll-up)
4. **Edge Plane**: GPU/CPU workers, relays, tunnels (Docker, Coolify agents)
5. **Observability**: Metrics, logs, traces (InfluxDB 3, Grafana 10, Loki)

## Core Components

### Global Scheduler

The scheduler is responsible for distributing workloads to the most appropriate edge nodes:

- **Load Balancing Algorithm**: Capability filter → latency score → earnings weight (Pareto front)
- **Error Handling**: If a job fails twice on different nodes, it's escalated to the cloud overflow queue
- **Autoscaling**: KEDA watches Postgres `pending_jobs` table and scales 1→10 pods as needed

### Credit Ledger

The ledger tracks all financial transactions in the system:

- **Schema**: `accounts`, `ledger_entries`, `usage_events`
- **Atomicity**: DB transaction wraps job dispatch + creator debit to avoid credit overdraft
- **Export**: Nightly dump to Parquet in R2 for BI; GDPR erase via account ID filter

### Billing Service

Handles payment processing and credit management:

- Listens to Stripe `checkout.session.completed` events
- Maps Price ID → credits via ENV
- Ensures idempotency by session ID

## Edge Components

### Edge Relay

The relay facilitates communication between the scheduler and worker containers:

- **Startup**: Pulls latest `relay` image, verifies SHA-256 checklist pinned in Blueprint
- **Security**: Mutual-TLS to Cloudflare tunnel OR direct WireGuard if on-prem
- **Sandbox**: Docker rootless + seccomp; upcoming migration to Firecracker

### Workload Containers

Various container types handle different workloads:

| Job Type             | Base Image                              | GPU RAM     | ETA Example      |
| -------------------- | --------------------------------------- | ----------- | ---------------- |
| Storyboard (SD-XL)   | `cheddarfox/rendertrust-comfyui:cu12.1` | 12 GB       | 4 s / frame      |
| LLM (Ollama Mixtral) | `ollama/ollama:0.1`                     | 0 / CPU opt | 80 tokens/s      |
| Voice (OpenVoice)    | `cheddarfox/rendertrust-voice:onnx`     | 6 GB        | 30 s / 10 s clip |

### Node Poller

Monitors the health and status of edge nodes:

- Collects GPU mem/temp/util + container count
- Pushes Influx line protocol via UDP to reduce overhead (<1 KB)
- Node considered offline if heartbeat >90 s

## Deployment

### Environment Setup

| Layer             | Tech                         | Host                                      | Notes                             |
| ----------------- | ---------------------------- | ----------------------------------------- | --------------------------------- |
| **Control Plane** | Coolify-core v4              | 8-core VPS, 32 GB RAM, 200 GB SSD         | Public IP + CF proxy              |
| **Data Plane**    | PostgreSQL 15                | Same VPS (dev) / Cloud SQL (prod)         | 2 vCPU / 8 GB RAM                 |
|                   | S3-compatible (MinIO or R2)  | MinIO Docker (dev) / Cloudflare R2 (prod) | Private bucket `rendertrust-jobs` |
| **Secrets**       | Vault 1.15                   | Docker on VPS                             | TLS via CF Origin Cert            |
| **Observability** | Grafana 10 + Influx 3        | Docker                                    | Dashboards 9119/9120              |
| **CI/CD**         | GitHub Actions → Coolify API | —                                         | Deploy tags to staging/prod       |

Edge nodes require:

- **GPU tier**: NVIDIA RTX 3060+ (12 GB) OR CPU-only (≥4 cores)
- Docker 24 + NVIDIA Container Toolkit
- Outbound HTTPS (no inbound ports)

### Bootstrap Process

1. **Core Host** (~30 min)
   - Provision Ubuntu 22.04 VPS on Hetzner CAX31
   - Update packages & enable UFW allow `22,80,443`
   - Install Docker & Docker Compose v2
   - Install Coolify: `curl -fsSL https://get.coollabs.io/coolify/install.sh | bash`
   - Add domain `coolify.rendertrust.com` in Cloudflare → orange-cloud; issue origin cert

2. **Vault + Terraform** (~15 min)

   ```bash
   cd infra/vault && docker compose up -d
   export VAULT_ADDR=https://vault.rendertrust.com
   export VAULT_TOKEN=$(cat .root_token)
   terraform -chdir=terraform init && terraform apply -auto-approve
   ```

3. **Core Platform Deploy** (~10 min)

   ```bash
   coolify deploy --project core-platform \
     --env POSTGRES_URL=postgres://... \
     --env VAULT_ADDR=$VAULT_ADDR \
     --env STRIPE_SECRET=sk_live_xxx ...
   ```

4. **Edge Blueprint Publish**
   ```bash
   coolify blueprints publish edgekit-v0.4 edgekit_v0.4.yaml
   ```

## Security

| Threat                        | Control                                       | Residual Risk                     |
| ----------------------------- | --------------------------------------------- | --------------------------------- |
| Rogue node exfiltrates script | AES-GCM encryption + audit hash               | Low (must break AES)              |
| JWT stolen                    | 24 h TTL, device fingerprint, revocation list | Very Low                          |
| Supply-chain attack           | Image digest pin + Trivy scan in CI           | Low                               |
| Edge container escape         | Rootless Docker + seccomp                     | Medium (will move to Firecracker) |

Pen-tests are scheduled each quarter; the last report (04-2025) had zero critical findings.

## Monitoring

- **Grafana dashboards**
  - `Fleet Overview` – VRAM, temp, uptime, earnings
  - `Job Latency` – p95 dispatch & runtime

- **Prometheus alerts**
  - Edge temp > 85 °C for 5 min → `#ops-pager`
  - Scheduler CPU > 75% for 10 min

## Disaster Recovery

| Asset    | Backup                 | RPO    | Restore                                |
| -------- | ---------------------- | ------ | -------------------------------------- |
| Postgres | WAL + nightly snapshot | 15 min | Ansible script `pg-restore.yml`        |
| S3 Jobs  | R2 CRR to EU           | 1 h    | Point app to secondary bucket          |
| Vault    | Raft snapshots hourly  | 1 h    | `vault operator raft snapshot restore` |

DR drills are conducted every 6 months.

---

## Contact & Support

For implementation assistance or questions:

- **Email**: [scott@wordstofilmby.com](mailto:scott@wordstofilmby.com)
- **Website**: [www.WordsToFilmBy.com](https://www.wordstofilmby.com)

RenderTrust is sponsored by [Words To Film By](https://www.wordstofilmby.com), empowering creators with secure, distributed AI infrastructure.

For more detailed information, refer to the [RenderTrust Architect Manual](../RenderTrust_Architect_Manual.md).
