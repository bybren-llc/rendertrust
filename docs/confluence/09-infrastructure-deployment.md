# Infrastructure & Deployment

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Deployment Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Cloudflare                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ DNS: api.rendertrust.com → CNAME tunnel.cfargotunnel │   │
│  │ SSL: Full (strict), TLS 1.2+, HSTS preload          │   │
│  │ WAF: SQLi, XSS, path traversal rules                │   │
│  │ Rate Limit: 100/min API, 20/min auth                 │   │
│  └──────────────────────────────────────────────────────┘   │
└────────────────────────────┬────────────────────────────────┘
                             │ (Cloudflare Tunnel, outbound)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 Hetzner VPS (CX31+)                          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Coolify (Self-hosted PaaS)               │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌───────────────┐ │   │
│  │  │FastAPI │ │  PG 16 │ │Redis 7 │ │Cloudflare     │ │   │
│  │  │Gateway │ │        │ │        │ │Tunnel Daemon  │ │   │
│  │  │ :8000  │ │ :5432  │ │ :6379  │ │               │ │   │
│  │  └────────┘ └────────┘ └────────┘ └───────────────┘ │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌───────────────┐ │   │
│  │  │Promethe│ │Grafana │ │  Loki  │ │  Promtail     │ │   │
│  │  │ :9090  │ │ :3000  │ │ :3100  │ │               │ │   │
│  │  └────────┘ └────────┘ └────────┘ └───────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Coolify Setup

### Server Requirements

| Spec | Minimum | Recommended |
|------|---------|-------------|
| **CPU** | 2 vCPU | 4 vCPU |
| **RAM** | 4 GB | 8 GB |
| **Disk** | 40 GB SSD | 80 GB SSD |
| **OS** | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |
| **Provider** | Hetzner CX21 | Hetzner CX31 |

### Installation

```bash
# Install Coolify (installs Docker, Traefik, Coolify UI)
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash

# Access Coolify UI
open http://<server-ip>:8000
```

### Project Setup

1. Create project "RenderTrust" in Coolify
2. Add Docker Compose resource → `ci/coolify/docker-compose.coolify.yml`
3. Set environment variables from `ci/coolify/env.template`
4. Configure domain: `api.rendertrust.com` → Let's Encrypt SSL
5. Deploy

---

## Docker Compose Variants

| File | Purpose | Key Features |
|------|---------|--------------|
| `docker-compose.yml` | Development | Hot reload, no resource limits |
| `docker-compose.prod.yml` | Production | Resource limits, security hardening, read-only rootfs |
| `docker-compose.test.yml` | Testing | Ephemeral DB/Redis (tmpfs), auto-runs pytest |
| `docker-compose.edge.yml` | Edge nodes | Single node service with health check |
| `loadtest/docker-compose.load.yml` | Load testing | k6 + target app + monitoring |

### Production Hardening (`docker-compose.prod.yml`)

| Feature | Configuration |
|---------|--------------|
| **Resource Limits** | App: 1GB/1 CPU, DB: 1GB/1 CPU, Redis: 512MB/0.5 CPU |
| **Security Options** | `no-new-privileges: true` |
| **Filesystem** | Read-only rootfs + 100MB tmpfs for app |
| **Logging** | JSON driver, 50MB max, 5 file rotation |
| **Redis** | Appendonly, 256MB maxmemory, allkeys-lru |
| **PostgreSQL** | 128MB shared_buffers, persistent volume |

---

## Cloudflare Configuration

### DNS Records

| Record | Type | Value | Proxy |
|--------|------|-------|-------|
| `api.rendertrust.com` | CNAME | `{tunnel}.cfargotunnel.com` | ON |
| `app.rendertrust.com` | CNAME | `{tunnel}.cfargotunnel.com` | ON |
| `grafana.rendertrust.com` | CNAME | `{tunnel}.cfargotunnel.com` | ON |
| `@` | TXT | `v=spf1 -all` | — |
| `_dmarc` | TXT | `v=DMARC1; p=reject` | — |

### Tunnel Configuration

- **Connection**: Outbound-only from VPS to Cloudflare edge
- **No inbound ports** needed on VPS (except SSH for admin)
- **Auth**: Credential file at `~/.cloudflared/{tunnel-id}.json` OR token-based
- **Catch-all**: Returns 404 for unrecognized hostnames

### SSL/TLS

- Mode: **Full (strict)** — encrypted client→CF and CF→origin with cert validation
- TLS 1.2 minimum, TLS 1.3 enabled
- HSTS: 6 months, includeSubDomains, preload
- Automatic HTTPS rewrites: enabled

---

## Monitoring Stack

### Prometheus

Scrapes metrics from the FastAPI app every 15 seconds:

```yaml
# ci/grafana/prometheus.yml
scrape_configs:
  - job_name: rendertrust-app
    static_configs:
      - targets: ["app:8000"]
    metrics_path: /metrics
    scrape_interval: 15s
```

### Grafana Dashboards

Auto-provisioned dashboards for:

| Dashboard | Panels |
|-----------|--------|
| **API Performance** | Request rate, latency p50/p95/p99, error rate, status codes |
| **Job Pipeline** | Dispatch rate, completion rate, failure rate, queue depth |
| **Fleet Health** | Node count by status, average load, heartbeat freshness |
| **Credits** | Credit consumption rate, balance distribution, purchase volume |

### Alerting Rules

| Alert | Condition | Severity | Duration |
|-------|-----------|----------|----------|
| **FleetTooFewNodes** | healthy nodes < 2 | Critical | 5 min |
| **HighErrorRate** | 5xx rate > 5% | Critical | 5 min |
| **HighJobFailureRate** | Failed > 10% | Warning | 10 min |
| **APILatencyHigh** | p95 > 5s | Warning | 5 min |
| **NoWebSocketConnections** | connections == 0 | Warning | 10 min |

### Logging (Loki + Promtail)

**Log Pipeline:**
```
Docker containers → Promtail → Loki → Grafana
```

**Promtail Configuration:**
- Scrapes Docker container logs via socket
- Extracts JSON fields: `level`, `event`, `request_id`, `timestamp`
- Labels: `service`, `container_name`

**Loki Configuration:**
- BoltDB shipper + filesystem storage
- 30-day retention (720 hours)
- Max 5000 entries per query

**Example LogQL Queries:**
```
# All errors
{service="core"} | json | level="error"

# Trace a specific request
{service="core"} | json | request_id="abc-123"

# Stripe webhook events
{service="core"} | json | event=~"stripe.*"

# Error rate over 5 minutes
rate({service="core"} | json | level="error" [5m])
```

---

## CI/CD Pipeline

### GitHub Actions Workflow

```
Push to dev/PR
    │
    ▼
┌─────────────────────────────────────┐
│         Stage 1: Quality            │
│  ┌─────────┐  ┌─────────────────┐  │
│  │  Lint   │  │  Type Check     │  │
│  │  (ruff) │  │  (mypy)         │  │
│  └─────────┘  └─────────────────┘  │
└──────────────────┬──────────────────┘
                   │
    ▼              ▼              ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│  Unit    │ │Integration│ │   E2E    │
│  Tests   │ │  Tests    │ │  Tests   │
│ (SQLite) │ │ (PG+Redis)│ │ (Docker) │
└──────────┘ └──────────┘ └──────────┘
                   │
                   ▼
         ┌──────────────┐
         │ Docker Build  │
         │ (multi-stage) │
         └──────────────┘
```

### Security Scanning (Weekly + PR)

| Scan | Tool | Scope |
|------|------|-------|
| **Dependency Audit** | pip-audit | All Python deps |
| **SAST** | Semgrep | core/auth, core/api, core/config, core/database |
| **Secret Scanning** | Gitleaks | Entire repo |

### Deploy Script (`ci/deploy.sh`)

```bash
./ci/deploy.sh              # Standard deploy
./ci/deploy.sh --build      # Build from source
./ci/deploy.sh --no-migrate # Skip database migrations
./ci/deploy.sh --rollback   # Rollback to previous image
```

**Zero-downtime process:**
1. Save current image digest (for rollback)
2. Pull/build new image
3. Run migrations in ephemeral container
4. Restart services
5. Health check polling (30 retries × 2s)
6. If health check fails, automatic rollback

---

## Database Management

### Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "add column X"

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history
```

### Backups

Daily automated backups at 03:00 UTC:

```bash
# Manual backup
docker exec $(docker ps -q -f name=db) \
  pg_dump -U rendertrust rendertrust | gzip > backup-$(date +%Y%m%d).sql.gz

# Restore from backup
gunzip -c backup-20260313.sql.gz | \
  docker exec -i $(docker ps -q -f name=db) psql -U rendertrust rendertrust
```

Retention: 30 days local, recommended S3 sync for off-site.

---

## Disaster Recovery

### Procedures

1. **Database Corruption**: Restore from latest pg_dump backup
2. **Application Failure**: `./ci/deploy.sh --rollback`
3. **VPS Failure**: Provision new VPS, install Coolify, restore DB backup, deploy
4. **DNS/CDN Failure**: Direct-to-IP fallback (temporary)

### RTO/RPO Targets

| Metric | Target |
|--------|--------|
| **RPO** (data loss) | 24 hours (daily backups) |
| **RTO** (recovery time) | 1 hour (new VPS + restore) |

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
