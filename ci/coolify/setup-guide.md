# MIT License -- see LICENSE-MIT
#
# RenderTrust Coolify Deployment Setup Guide
#
# Step-by-step runbook for deploying RenderTrust on Coolify (self-hosted PaaS)
# running on a Hetzner VPS.
#
# Related tickets:
#   - REN-115: Coolify project setup (this guide)
#   - REN-116: Cloudflare Tunnel integration
#   - REN-120: Prometheus monitoring setup

## Prerequisites

- A Hetzner Cloud account (https://console.hetzner.cloud)
- A domain name with DNS managed by Cloudflare (for REN-116)
- SSH key pair for server access
- RenderTrust repository access (ByBren-LLC/rendertrust)

---

## Step 1: Provision the Hetzner VPS

1. Log in to Hetzner Cloud Console
2. Create a new server:
   - **Location**: Choose closest to your primary user base (e.g., Falkenstein for EU, Ashburn for US)
   - **Image**: Ubuntu 22.04 LTS
   - **Type**: CX31 or higher (4 vCPU, 8 GB RAM recommended; CX21 with 4 GB RAM is the minimum)
   - **Volume**: Add a 40 GB+ volume for persistent data (optional if using local disk)
   - **SSH Key**: Add your public key
   - **Firewall**: Create or assign a firewall with these rules:
     - Inbound TCP 22 (SSH) -- restrict to your IP if possible
     - Inbound TCP 80 (HTTP) -- required for Coolify and Let's Encrypt
     - Inbound TCP 443 (HTTPS) -- required for Coolify and application traffic
     - Inbound TCP 8000 (optional) -- direct app access for debugging
   - **Name**: `rendertrust-prod-01`

3. Note the server's public IP address after creation.

4. SSH into the server to verify access:

```bash
ssh root@<server-ip>
```

5. Update the system:

```bash
apt update && apt upgrade -y
reboot
```

---

## Step 2: Install Coolify

Coolify provides a one-liner installer that sets up Docker, Traefik, and the
Coolify management UI.

1. SSH into your server:

```bash
ssh root@<server-ip>
```

2. Run the Coolify installer:

```bash
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

3. Wait for installation to complete (2-5 minutes). The installer will:
   - Install Docker Engine
   - Set up the Coolify containers
   - Configure Traefik as a reverse proxy

4. Access the Coolify dashboard:
   - Open `http://<server-ip>:8000` in your browser
   - Create your admin account on first visit
   - **Important**: Change the default port or set up a domain for the Coolify UI itself

5. (Recommended) Secure the Coolify dashboard:
   - In Coolify Settings, configure a domain for the dashboard (e.g., `coolify.rendertrust.com`)
   - Enable HTTPS via Let's Encrypt

---

## Step 3: Create the RenderTrust Project in Coolify

1. In the Coolify dashboard, click **New Project**
2. Name it: `RenderTrust`
3. Add a new **Environment** (e.g., `production`)

### Connect the Git Repository

1. In the project, click **New Resource** > **Docker Compose**
2. Connect your GitHub account (or use a deploy key):
   - Repository: `ByBren-LLC/rendertrust`
   - Branch: `dev` (or the release branch)
3. Set the **Docker Compose file path** to: `ci/coolify/docker-compose.coolify.yml`
4. Set the **Build context** to the repository root (`.`)

---

## Step 4: Configure Environment Variables

1. In Coolify, navigate to the project's **Environment Variables** section
2. Use `ci/coolify/env.template` as your reference
3. Set the following **required** variables:

### Secrets (generate these)

```bash
# Run these commands locally to generate secure values:
openssl rand -hex 32  # Use output for SECRET_KEY
openssl rand -hex 32  # Use output for JWT_SECRET_KEY
openssl rand -hex 32  # Use output for POSTGRES_PASSWORD
```

### Required Variables

| Variable | Example Value | Notes |
|----------|--------------|-------|
| `SECRET_KEY` | (generated) | Application signing key |
| `JWT_SECRET_KEY` | (generated) | JWT token signing key |
| `POSTGRES_PASSWORD` | (generated) | PostgreSQL password |
| `APP_ENV` | `production` | Enables production security |
| `APP_DEBUG` | `false` | Must be false in production |
| `DATABASE_URL` | `postgresql+asyncpg://rendertrust:<pg-password>@db:5432/rendertrust` | Match POSTGRES_PASSWORD |
| `REDIS_URL` | `redis://redis:6379/0` | Default for companion service |

### Optional Variables (configure as needed)

| Variable | Notes |
|----------|-------|
| `STRIPE_SECRET_KEY` | Required for payment processing |
| `STRIPE_WEBHOOK_SECRET` | Required for Stripe webhooks |
| `STRIPE_PUBLISHABLE_KEY` | Required for frontend Stripe.js |
| `SENTRY_DSN` | Error tracking (recommended) |
| `POSTHOG_API_KEY` | Product analytics |
| `CORS_ORIGINS` | Set to your frontend domain |
| `S3_ENDPOINT` | Object storage endpoint |
| `S3_ACCESS_KEY` | Object storage access key |
| `S3_SECRET_KEY` | Object storage secret key |
| `S3_BUCKET` | Object storage bucket name |

4. Mark all secret values as **sensitive** in Coolify (hides them in the UI)

---

## Step 5: Deploy

1. In the Coolify dashboard, click **Deploy** on the RenderTrust project
2. Monitor the build logs:
   - Docker image build (multi-stage, may take 3-5 minutes on first deploy)
   - Container startup
   - Health check passing
3. Verify the deployment:

```bash
# From your local machine (replace with your server IP or domain)
curl -s https://api.rendertrust.com/health | jq .
# Expected: {"status": "healthy", "version": "0.1.0"}

curl -s https://api.rendertrust.com/version | jq .
# Expected: {"name": "rendertrust", "version": "0.1.0", "environment": "production"}
```

---

## Step 6: SSL/TLS Configuration

### Option A: Coolify Built-in (Let's Encrypt)

Coolify can automatically provision Let's Encrypt certificates via Traefik:

1. In the project settings, set the **Domain** to your API domain (e.g., `api.rendertrust.com`)
2. Point your DNS A record to the server IP
3. Coolify/Traefik will automatically obtain and renew certificates

### Option B: Cloudflare Tunnel (Recommended -- REN-116)

For enhanced security and DDoS protection, use a Cloudflare Tunnel instead
of exposing the server directly. This is covered in a separate story:

- **REN-116: Cloudflare Tunnel Integration**
- Benefits: No exposed ports (except 443 for the tunnel), Cloudflare WAF, DDoS protection
- The tunnel connects Cloudflare's edge to your Coolify server without opening inbound ports

Until REN-116 is implemented, use Option A.

---

## Step 7: Database Backup Configuration

### Automated Backups with pg_dump

1. SSH into the server:

```bash
ssh root@<server-ip>
```

2. Create a backup script:

```bash
cat > /opt/rendertrust-backup.sh << 'SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="/opt/backups/rendertrust"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/rendertrust_${TIMESTAMP}.sql.gz"
RETENTION_DAYS=30

mkdir -p "$BACKUP_DIR"

# Dump the database from the running PostgreSQL container
docker exec $(docker ps -q -f name=db) \
    pg_dump -U rendertrust rendertrust | gzip > "$BACKUP_FILE"

# Remove backups older than retention period
find "$BACKUP_DIR" -name "rendertrust_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "[backup] Created: ${BACKUP_FILE} ($(du -h "$BACKUP_FILE" | cut -f1))"
SCRIPT

chmod +x /opt/rendertrust-backup.sh
```

3. Add a cron job for daily backups:

```bash
# Run daily at 03:00 UTC
echo "0 3 * * * /opt/rendertrust-backup.sh >> /var/log/rendertrust-backup.log 2>&1" | crontab -
```

4. (Recommended) Copy backups off-server to S3-compatible storage:

```bash
# Install s3cmd or use the aws CLI to sync backups
# This should be configured once S3 storage is set up
# aws s3 sync /opt/backups/rendertrust/ s3://rendertrust-backups/
```

### Backup Verification

Test that backups are valid by periodically restoring to a test database:

```bash
# Create a test database and restore
gunzip -c /opt/backups/rendertrust/rendertrust_LATEST.sql.gz | \
    docker exec -i $(docker ps -q -f name=db) \
    psql -U rendertrust -d template1 -c "CREATE DATABASE restore_test;" && \
    docker exec -i $(docker ps -q -f name=db) \
    psql -U rendertrust restore_test

# Drop the test database after verification
docker exec $(docker ps -q -f name=db) \
    psql -U rendertrust -c "DROP DATABASE restore_test;"
```

---

## Step 8: Post-Deployment Verification Checklist

After the first successful deployment, verify:

- [ ] `/health` endpoint returns `{"status": "healthy"}`
- [ ] `/version` endpoint returns correct version and `"environment": "production"`
- [ ] Database migrations ran successfully (check container logs)
- [ ] Redis is connected (no Redis connection errors in logs)
- [ ] Swagger docs are NOT accessible at `/docs` (disabled in production)
- [ ] Security headers are present (X-Content-Type-Options, X-Frame-Options, HSTS)
- [ ] CORS only allows configured origins
- [ ] Application logs are structured JSON (structlog)
- [ ] Backup cron job is scheduled
- [ ] Coolify health monitoring shows green status

---

## Monitoring (Future -- REN-120)

Prometheus and Grafana monitoring will be added in a separate story:

- **REN-120: Prometheus Monitoring Setup**
- Will add: `/metrics` endpoint, Prometheus scrape config, Grafana dashboards
- For now, monitor via:
  - Coolify dashboard (container health, resource usage)
  - Application logs: `docker logs <container-id> --follow`
  - PostgreSQL logs: accessible via the db container

---

## Troubleshooting

### Container fails to start

```bash
# Check container logs
docker logs $(docker ps -aq -f name=app) --tail 100

# Common issues:
# - "SECRET_KEY must be changed in production" -- set SECRET_KEY env var
# - "connection refused" to db -- PostgreSQL not ready, check db container
# - "alembic.util.exc.CommandError" -- migration issue, check alembic logs
```

### Database connection issues

```bash
# Verify PostgreSQL is running and healthy
docker ps -f name=db
docker logs $(docker ps -aq -f name=db) --tail 50

# Test connectivity from the app container
docker exec -it $(docker ps -q -f name=app) \
    python -c "import asyncio, asyncpg; asyncio.run(asyncpg.connect('postgresql://rendertrust:PASSWORD@db:5432/rendertrust'))"
```

### Redis connection issues

```bash
# Verify Redis is running
docker exec $(docker ps -q -f name=redis) redis-cli ping
# Expected: PONG
```

### Redeploying

In Coolify, click **Redeploy** to rebuild and restart all services.
For zero-downtime deployments, consider enabling Coolify's rolling update feature.

---

## Architecture Notes

```
Internet
    |
    v
[Cloudflare] (REN-116)
    |
    v
[Hetzner VPS]
    |
    +-- [Coolify/Traefik] (reverse proxy, SSL termination)
    |       |
    |       v
    |   [app container] (FastAPI on port 8000)
    |       |
    |       +-- [db container] (PostgreSQL 16, volume: postgres_data)
    |       |
    |       +-- [redis container] (Redis 7, volume: redis_data)
    |
    +-- [Coolify UI] (management dashboard)
```

The app container runs the entrypoint script which:
1. Waits for PostgreSQL to accept connections
2. Runs Alembic migrations (`alembic upgrade head`)
3. Starts uvicorn with proxy headers enabled (for Traefik)
