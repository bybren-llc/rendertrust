# User Guide — Administrator

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Who Is This For?

This guide is for **administrators** who manage the RenderTrust platform — monitoring fleet health, managing infrastructure, responding to alerts, and performing operational tasks.

---

## Admin Responsibilities

1. **Fleet Management** — Monitor node health, handle unhealthy/offline nodes
2. **Infrastructure** — Manage Coolify deployment, database, Redis
3. **Monitoring** — Watch dashboards, respond to alerts
4. **Security** — Review WAF logs, manage Cloudflare rules
5. **Billing** — Investigate credit issues, manual adjustments
6. **Disaster Recovery** — Database backups, rollbacks

---

## Fleet Management

### Viewing Fleet Status

```bash
# Via API
curl https://api.rendertrust.com/api/v1/nodes \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

### Prometheus Metrics

| Metric | What to Watch |
|--------|---------------|
| `fleet_nodes_total{status="healthy"}` | Should be >= 2 |
| `fleet_nodes_total{status="unhealthy"}` | Should be 0 |
| `fleet_nodes_total{status="offline"}` | Track trends |
| `active_websocket_connections` | Should match healthy nodes |

### Node Health Decision Tree

```
Node reported UNHEALTHY?
├── Check error logs in Loki: {service="core"} | json | event=~"node.*"
├── 3+ consecutive job failures?
│   ├── Yes → Circuit breaker triggered. Check node operator logs.
│   └── No → Temporary issue, node will auto-recover on next heartbeat
└── No heartbeat for 5+ minutes?
    └── Node may be offline. Contact operator.
```

---

## Infrastructure Management

### Deployment

```bash
# Standard deploy (pull latest image, migrate, restart)
./ci/deploy.sh

# Build from source
./ci/deploy.sh --build

# Skip migrations (hotfix only)
./ci/deploy.sh --no-migrate

# Rollback to previous version
./ci/deploy.sh --rollback
```

### Service Health

```bash
# Readiness check (all dependencies)
curl https://api.rendertrust.com/api/v1/health/ready

# Expected response
{
  "status": "ready",
  "checks": {
    "database": "connected",
    "redis": "connected"
  }
}

# If degraded, check individual services:
docker compose ps
docker compose logs app --tail 50
docker compose logs db --tail 50
docker compose logs redis --tail 50
```

### Database Operations

```bash
# Run pending migrations
alembic upgrade head

# Check migration status
alembic current

# View migration history
alembic history

# Manual backup
docker exec $(docker ps -q -f name=db) \
  pg_dump -U rendertrust rendertrust | gzip > backup-$(date +%Y%m%d).sql.gz

# Restore from backup
gunzip -c backup-20260313.sql.gz | \
  docker exec -i $(docker ps -q -f name=db) psql -U rendertrust rendertrust

# Connect to database shell
docker exec -it $(docker ps -q -f name=db) psql -U rendertrust rendertrust
```

### Redis Operations

```bash
# Connect to Redis CLI
docker exec -it $(docker ps -q -f name=redis) redis-cli

# Check queue depth for a node
LLEN queue:node:<node-uuid>

# Check blacklisted tokens
KEYS blacklist:*

# Memory usage
INFO memory
```

---

## Monitoring

### Grafana Dashboards

Access: `https://grafana.rendertrust.com` (protected by Cloudflare Access)

| Dashboard | Key Panels |
|-----------|-----------|
| **API Performance** | Request rate, p50/p95/p99 latency, error rate by status code |
| **Job Pipeline** | Dispatch rate, completion rate, failure rate, avg execution time |
| **Fleet Health** | Node count by status, avg load, heartbeat freshness |
| **Credits** | Consumption rate, balance distribution, purchase volume |

### Alert Response Procedures

#### FleetTooFewNodes (Critical, 5 min)

**Condition**: Less than 2 healthy nodes

**Steps**:
1. Check `fleet_nodes_total` metric breakdown by status
2. Query Loki: `{service="core"} | json | event=~"node.*unhealthy|offline"`
3. If nodes went unhealthy: check job failure logs for root cause
4. If nodes went offline: check WebSocket connection logs
5. Contact node operators if needed
6. Consider temporarily relaxing circuit breaker thresholds

#### HighErrorRate (Critical, 5 min)

**Condition**: 5xx error rate > 5%

**Steps**:
1. Check Grafana for error rate spike timing
2. Query Loki: `{service="core"} | json | level="error" | line_format "{{.event}}"`
3. Check if specific endpoint is failing: group by `endpoint` label
4. Check database connectivity: `GET /api/v1/health/ready`
5. If database issue: check PG logs, disk space, connection pool
6. If Redis issue: check Redis logs, memory
7. If application bug: rollback with `./ci/deploy.sh --rollback`

#### HighJobFailureRate (Warning, 10 min)

**Condition**: Failed jobs > 10% of completions

**Steps**:
1. Check which job types are failing
2. Query: `{service="core"} | json | event="job_failed"`
3. Check if specific nodes are causing failures (circuit breaker)
4. Review dead letter queue for patterns
5. If node-specific: mark node unhealthy, investigate with operator

#### APILatencyHigh (Warning, 5 min)

**Condition**: p95 latency > 5 seconds

**Steps**:
1. Check which endpoints are slow
2. Query: slow query logs in Loki
3. Check database: `pg_stat_activity` for long-running queries
4. Check Redis: `SLOWLOG GET 10`
5. Check connection pool exhaustion: `DB_POOL_SIZE` vs active connections

#### NoWebSocketConnections (Warning, 10 min)

**Condition**: Zero active WebSocket connections

**Steps**:
1. Check if any nodes are registered and online
2. Verify relay server is accepting connections
3. Check Cloudflare tunnel status
4. Test WebSocket connectivity from a node

---

### Log Queries (Loki/LogQL)

```bash
# All errors in last hour
{service="core"} | json | level="error"

# Trace a specific request
{service="core"} | json | request_id="abc-123"

# Stripe webhook events
{service="core"} | json | event=~"stripe.*"

# Node registrations
{service="core"} | json | event="node_registered"

# Job dispatch failures
{service="core"} | json | event="dispatch_failed"

# Authentication failures (potential brute force)
{service="core"} | json | event="login_failed"

# Error rate over 5 minutes
rate({service="core"} | json | level="error" [5m])

# Top 10 error events
topk(10, sum by (event) (rate({service="core"} | json | level="error" [1h])))
```

---

## Security Operations

### Cloudflare WAF

Access: Cloudflare Dashboard → Security → WAF

**Review regularly**:
- Blocked requests (SQLi, XSS, path traversal)
- Rate limited IPs
- Challenged requests (suspicious UAs)

**Emergency: Block an IP**:
1. Cloudflare Dashboard → Security → WAF → Custom Rules
2. Add rule: `ip.src == X.X.X.X` → Block

### Secret Rotation

**JWT Secret Key**:
```bash
# Generate new key
openssl rand -hex 32

# Update in Coolify env vars
# Redeploy (existing tokens will be invalidated)
```

**Stripe Webhook Secret**:
1. Regenerate in Stripe Dashboard → Webhooks
2. Update `STRIPE_WEBHOOK_SECRET` in Coolify
3. Redeploy

**Database Password**:
1. Update PostgreSQL password
2. Update `DATABASE_URL` in Coolify
3. Redeploy

### Credit Adjustments

For manual credit adjustments (refunds, corrections):

```bash
curl -X POST https://api.rendertrust.com/api/v1/credits/deduct \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "50.0000",
    "reference_id": "admin-refund-2026-03-13-001",
    "description": "Refund: billing error for user X"
  }'
```

Use unique `reference_id` values — the operation is idempotent.

---

## Disaster Recovery

### Backup Schedule

| What | Frequency | Retention | Location |
|------|-----------|-----------|----------|
| PostgreSQL dump | Daily 03:00 UTC | 30 days | Local + S3 |
| Redis AOF | Continuous | Current only | Container volume |
| Application config | Per deploy | Git history | GitHub |

### Recovery Procedures

#### Database Corruption

```bash
# 1. Stop application
docker compose stop app

# 2. Restore from latest backup
gunzip -c backup-YYYYMMDD.sql.gz | \
  docker exec -i $(docker ps -q -f name=db) psql -U rendertrust rendertrust

# 3. Run any pending migrations
docker compose run --rm app alembic upgrade head

# 4. Restart application
docker compose start app
```

#### Application Rollback

```bash
./ci/deploy.sh --rollback
```

#### Complete Server Recovery

1. Provision new Hetzner VPS (CX31+, Ubuntu 22.04)
2. Install Coolify: `curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash`
3. Restore database from off-site backup
4. Set environment variables in Coolify
5. Deploy application
6. Update Cloudflare tunnel to point to new server
7. Verify health: `curl /api/v1/health/ready`

---

## Maintenance Checklist

### Daily
- [ ] Check Grafana dashboards for anomalies
- [ ] Review alert notifications
- [ ] Verify backup completed successfully

### Weekly
- [ ] Review Cloudflare WAF blocked requests
- [ ] Check dependency audit results (CI security workflow)
- [ ] Review dead letter queue for patterns
- [ ] Check disk space on VPS

### Monthly
- [ ] Rotate secrets (JWT, Stripe, DB password)
- [ ] Review and prune old backups
- [ ] Review node operator reports
- [ ] Process monthly payouts
- [ ] Review resource utilization (scale up/down?)

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
