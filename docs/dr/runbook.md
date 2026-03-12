<!-- MIT License -- see LICENSE-MIT -->

# RenderTrust Disaster Recovery Runbook

**Document Owner**: Platform Engineering
**Last Updated**: 2026-03-12
**Review Cadence**: Quarterly
**Parent Epic**: REN-4 (Disaster Recovery)

---

## Recovery Objectives

| Metric | Target | Notes |
|--------|--------|-------|
| **RPO (Recovery Point Objective)** | 24 hours (database) | Daily automated backups via `scripts/backup-cron.sh` |
| **RPO (Job Artifacts)** | 1 hour | S3-compatible storage with cross-region replication |
| **RTO (Recovery Time Objective)** | 4 hours | Full environment rebuild from scratch |

---

## Backup Inventory

| Component | Backup Method | Frequency | Retention | Storage Location |
|-----------|--------------|-----------|-----------|-----------------|
| PostgreSQL 16 | `pg_dump` custom format + WAL archiving | Daily (02:00 UTC) | 30 days | S3 backup bucket + 7-day local |
| Redis 7 | AOF + RDB snapshot | Continuous (AOF), hourly (RDB) | 7 days | S3 backup bucket |
| S3/R2 Objects | Cross-region replication or `rclone sync` | Continuous | Same as source | Secondary region |
| Application Config | Manual export + version control | On change | Indefinite | Git repo + encrypted S3 |
| TLS Certificates | Automated via Coolify/Let's Encrypt | On renewal | N/A | Coolify config backup |
| Cloudflare Tunnel Credentials | Manual export | On change | Indefinite | Encrypted S3 |

---

## Section 1: PostgreSQL Backup Procedures

### 1.1 Automated Daily Backup (pg_dump)

The primary backup mechanism uses `scripts/backup-db.sh` which runs nightly via cron.

```bash
# Manual invocation
./scripts/backup-db.sh --upload --retention-days 7

# Verify backup exists
aws s3 ls s3://${BACKUP_S3_BUCKET}/db/ --recursive | tail -5
```

**Backup format**: PostgreSQL custom format (compressed), filename pattern: `rendertrust_db_YYYYMMDD_HHMMSS.dump`

### 1.2 WAL Archiving Configuration

For point-in-time recovery (PITR), configure WAL archiving in `postgresql.conf`:

```ini
# WAL archiving for PITR
wal_level = replica
archive_mode = on
archive_command = 'aws s3 cp %p s3://${BACKUP_S3_BUCKET}/wal/%f'
archive_timeout = 300
```

Ensure the PostgreSQL container or host has AWS CLI configured with appropriate credentials.

### 1.3 Backup Verification

After each backup, verify integrity:

```bash
# Verify backup is valid and list contents
pg_restore --list <dump_file> > /dev/null 2>&1 && echo "VALID" || echo "CORRUPT"

# Check file size is reasonable (should be > 1KB for non-empty DB)
ls -lh <dump_file>

# Optional: restore to a scratch database to verify
createdb rendertrust_verify
pg_restore --dbname=rendertrust_verify --clean --if-exists <dump_file>
psql -d rendertrust_verify -c "SELECT count(*) FROM alembic_version;"
dropdb rendertrust_verify
```

---

## Section 2: Redis Backup

### 2.1 AOF (Append-Only File)

Redis is configured with AOF persistence for durability:

```ini
# redis.conf
appendonly yes
appendfsync everysec
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb
```

### 2.2 RDB Snapshots

RDB snapshots provide point-in-time backups:

```ini
# redis.conf
save 3600 1
save 300 100
save 60 10000
dbfilename dump.rdb
```

### 2.3 Backup Procedure

```bash
# Trigger a manual RDB save
redis-cli BGSAVE

# Wait for save to complete
redis-cli LASTSAVE

# Copy AOF and RDB files to backup location
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
cp /var/lib/redis/appendonly.aof /backup/redis/appendonly_${TIMESTAMP}.aof
cp /var/lib/redis/dump.rdb /backup/redis/dump_${TIMESTAMP}.rdb

# Upload to S3
aws s3 cp /backup/redis/appendonly_${TIMESTAMP}.aof s3://${BACKUP_S3_BUCKET}/redis/
aws s3 cp /backup/redis/dump_${TIMESTAMP}.rdb s3://${BACKUP_S3_BUCKET}/redis/
```

### 2.4 Redis Restore

```bash
# Stop Redis
systemctl stop redis

# Replace AOF file
cp /backup/redis/appendonly_<TIMESTAMP>.aof /var/lib/redis/appendonly.aof
chown redis:redis /var/lib/redis/appendonly.aof

# Start Redis (it will replay the AOF)
systemctl start redis

# Verify
redis-cli PING
redis-cli DBSIZE
```

---

## Section 3: S3/R2 Object Backup

### 3.1 Cross-Region Replication (Preferred)

If using Cloudflare R2 or AWS S3, enable cross-region replication at the bucket level. This provides automatic, continuous backup of all objects.

### 3.2 rclone Sync (Alternative)

For manual or scheduled sync to a secondary location:

```bash
# Configure rclone remote (one-time setup)
rclone config create backup-dest s3 \
  provider=Other \
  access_key_id=${BACKUP_S3_ACCESS_KEY} \
  secret_access_key=${BACKUP_S3_SECRET_KEY} \
  endpoint=${BACKUP_S3_ENDPOINT}

# Sync primary bucket to backup
rclone sync primary:${S3_BUCKET} backup-dest:${BACKUP_S3_BUCKET}/s3-mirror/ \
  --transfers 16 \
  --checkers 32 \
  --log-file /var/log/rendertrust/rclone-sync.log \
  --log-level INFO

# Verify sync
rclone check primary:${S3_BUCKET} backup-dest:${BACKUP_S3_BUCKET}/s3-mirror/
```

### 3.3 Cron Schedule

```cron
# Sync S3 objects every hour
0 * * * * /usr/local/bin/rclone sync primary:${S3_BUCKET} backup-dest:${BACKUP_S3_BUCKET}/s3-mirror/ --log-file /var/log/rendertrust/rclone-sync.log --log-level INFO
```

---

## Section 4: Application Config Backup

### 4.1 Environment Variables

**Critical env vars** (stored in Coolify or `.env` on the host):

- `DATABASE_URL` -- PostgreSQL connection string
- `REDIS_URL` -- Redis connection string
- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` -- Payment credentials
- `JWT_SECRET_KEY` -- Authentication secret
- `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` / `S3_ENDPOINT` -- Object storage
- `POSTHOG_API_KEY` -- Analytics
- `CLOUDFLARE_TUNNEL_TOKEN` -- Tunnel credentials

**Backup procedure**:

```bash
# Export Coolify environment (via Coolify API or manual export)
# NEVER commit secrets to git -- use encrypted storage

# Encrypt and upload to S3
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
tar czf - .env | gpg --symmetric --cipher-algo AES256 -o /tmp/env_backup_${TIMESTAMP}.tar.gz.gpg
aws s3 cp /tmp/env_backup_${TIMESTAMP}.tar.gz.gpg s3://${BACKUP_S3_BUCKET}/config/
rm /tmp/env_backup_${TIMESTAMP}.tar.gz.gpg
```

### 4.2 TLS Certificates

Coolify manages Let's Encrypt certificates automatically. On recovery, Coolify will re-provision certificates. No manual backup required, but note:

- Custom certificates (if any) should be stored in encrypted S3
- Cloudflare origin certificates are managed in the Cloudflare dashboard

### 4.3 Cloudflare Tunnel Credentials

```bash
# Tunnel credentials file location (if using cloudflared directly)
# Typically: /etc/cloudflared/<tunnel-id>.json
# Back up to encrypted S3 alongside env vars
```

---

## Section 5: Full Recovery Procedure

**Scenario**: Complete loss of the primary Hetzner VPS. Must rebuild from scratch.

**Estimated time**: 2-4 hours

### Step 1: Provision New VPS (15 min)

1. Log in to Hetzner Cloud Console
2. Create new server:
   - **Type**: CPX31 (or equivalent to lost server)
   - **Location**: Same as original (or nearest alternative)
   - **Image**: Ubuntu 22.04 LTS
   - **SSH Key**: Add team SSH keys
3. Note the new server IP address

### Step 2: Install Coolify (20 min)

```bash
# SSH into new server
ssh root@<NEW_SERVER_IP>

# Install Coolify (official one-liner)
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash

# Wait for Coolify to start, then access at https://<NEW_SERVER_IP>:8000
# Complete initial setup (admin account, etc.)
```

### Step 3: Restore Application Config (15 min)

```bash
# Download encrypted env backup from S3
aws s3 cp s3://${BACKUP_S3_BUCKET}/config/env_backup_<LATEST>.tar.gz.gpg /tmp/
gpg --decrypt /tmp/env_backup_<LATEST>.tar.gz.gpg | tar xzf - -C /opt/rendertrust/

# Import environment variables into Coolify
# Use Coolify UI or API to set environment variables for each service
```

### Step 4: Deploy Application via Coolify (20 min)

1. In Coolify, connect to the GitHub repository (ByBren-LLC/rendertrust)
2. Configure build settings (Dockerfile, branch: `dev`)
3. Set environment variables from the restored config
4. Deploy the application

### Step 5: Restore PostgreSQL Database (30 min)

```bash
# Download latest backup from S3
aws s3 ls s3://${BACKUP_S3_BUCKET}/db/ | sort | tail -1
aws s3 cp s3://${BACKUP_S3_BUCKET}/db/rendertrust_db_<LATEST>.dump /tmp/

# Restore using the restore script
./scripts/restore-db.sh /tmp/rendertrust_db_<LATEST>.dump

# Or manually:
pg_restore --host=localhost --port=5432 --username=rendertrust \
  --dbname=rendertrust --clean --if-exists \
  /tmp/rendertrust_db_<LATEST>.dump

# Verify migration state
psql -d rendertrust -c "SELECT * FROM alembic_version;"

# Apply any pending migrations
cd /opt/rendertrust && alembic upgrade head
```

### Step 6: Restore Redis (10 min)

```bash
# Download latest Redis backup
aws s3 cp s3://${BACKUP_S3_BUCKET}/redis/appendonly_<LATEST>.aof /var/lib/redis/appendonly.aof
chown redis:redis /var/lib/redis/appendonly.aof

# Restart Redis
systemctl restart redis

# Verify
redis-cli PING
redis-cli DBSIZE
```

### Step 7: Verify Application (30 min)

```bash
# Health check
curl -f https://api.rendertrust.com/health || echo "HEALTH CHECK FAILED"

# Verify database connectivity
curl -f https://api.rendertrust.com/api/v1/status || echo "API STATUS FAILED"

# Verify key endpoints
curl -s https://api.rendertrust.com/api/v1/credits/balance -H "Authorization: Bearer <test-token>"

# Run smoke test suite (if available)
pytest tests/smoke/ -v

# Check logs for errors
docker logs rendertrust-api --tail 100
```

### Step 8: Update DNS (10 min)

1. Log in to Cloudflare dashboard
2. Update A/AAAA records to point to new server IP (if not using Cloudflare Tunnel)
3. If using Cloudflare Tunnel, update tunnel configuration to point to new server
4. Verify DNS propagation: `dig api.rendertrust.com`

### Step 9: Restore Cron Jobs (5 min)

```bash
# Re-install backup cron
crontab -l > /tmp/crontab.bak 2>/dev/null || true
echo "0 2 * * * /opt/rendertrust/scripts/backup-cron.sh" >> /tmp/crontab.bak
crontab /tmp/crontab.bak

# Verify
crontab -l
```

### Step 10: Post-Recovery Validation (30 min)

- [ ] Application responds to health checks
- [ ] Users can authenticate (JWT validation)
- [ ] Database queries return expected data
- [ ] Stripe webhooks are receiving events
- [ ] Redis caching is operational
- [ ] S3 object access works
- [ ] Backup cron is scheduled
- [ ] Monitoring/alerting is reconnected
- [ ] PostHog events are flowing

---

## Section 6: Partial Recovery Scenarios

### 6.1 Database Corruption Only

**Symptoms**: Application errors referencing database integrity, failed queries, ORM exceptions.

```bash
# 1. Stop application to prevent further writes
docker stop rendertrust-api

# 2. Assess damage
psql -d rendertrust -c "SELECT count(*) FROM pg_stat_activity;"
psql -d rendertrust -c "\dt+"  # Check table sizes

# 3. Restore from latest backup
./scripts/restore-db.sh <latest_dump_file_or_s3_path>

# 4. Apply any pending migrations
alembic upgrade head

# 5. Restart application
docker start rendertrust-api

# 6. Verify
curl -f https://api.rendertrust.com/health
```

**Data loss window**: Up to 24 hours (last backup). Consider WAL replay for point-in-time recovery if WAL archiving is enabled.

### 6.2 Redis Failure Only

**Symptoms**: Slow responses, cache misses, session issues, queue processing stalled.

```bash
# 1. Check Redis status
redis-cli PING
systemctl status redis

# 2. If Redis is down, attempt restart
systemctl restart redis

# 3. If data is corrupt, restore from backup
systemctl stop redis
cp /backup/redis/appendonly_<LATEST>.aof /var/lib/redis/appendonly.aof
chown redis:redis /var/lib/redis/appendonly.aof
systemctl start redis

# 4. If no backup available, flush and let the app repopulate
redis-cli FLUSHALL
systemctl restart redis

# 5. Verify
redis-cli PING
redis-cli DBSIZE
```

**Impact**: Redis loss is recoverable without data loss to the application. Caches and queues will repopulate. Active job dispatches may need to be re-queued.

### 6.3 S3 Data Loss

**Symptoms**: 404 errors on object retrieval, missing render artifacts.

```bash
# 1. Check S3 bucket status
aws s3 ls s3://${S3_BUCKET}/ --summarize

# 2. If cross-region replication is configured, sync from replica
rclone sync backup-dest:${BACKUP_S3_BUCKET}/s3-mirror/ primary:${S3_BUCKET}/ \
  --transfers 16 \
  --log-file /var/log/rendertrust/s3-restore.log

# 3. If no replication, restore from rclone backup
aws s3 sync s3://${BACKUP_S3_BUCKET}/s3-mirror/ s3://${S3_BUCKET}/

# 4. Verify
aws s3 ls s3://${S3_BUCKET}/ --summarize
```

**Data loss window**: Up to 1 hour (hourly rclone sync).

### 6.4 Application Crash (No Data Loss)

**Symptoms**: Application not responding, container crashed, OOM kill.

```bash
# 1. Check container status
docker ps -a | grep rendertrust

# 2. Check logs for root cause
docker logs rendertrust-api --tail 200

# 3. Restart the application
docker restart rendertrust-api

# 4. If OOM, check memory and increase limits
docker stats rendertrust-api
# Update docker-compose.yml memory limits if needed

# 5. If code issue, redeploy from known-good commit
cd /opt/rendertrust
git log --oneline -5
git checkout <known-good-commit>
docker compose up -d --build

# 6. Verify
curl -f https://api.rendertrust.com/health
```

---

## Section 7: Testing Schedule

### 7.1 Monthly DR Drill

**Frequency**: First Monday of each month
**Duration**: 1-2 hours
**Scope**: Partial recovery test

**Procedure**:

1. Verify latest backup exists and is recent (< 24 hours old)
2. Download backup to a test environment
3. Restore database to a scratch instance
4. Verify row counts match production (within expected delta)
5. Verify Alembic migration version matches
6. Document results in Linear ticket

**Checklist**:

- [ ] Backup file exists in S3
- [ ] Backup file is less than 24 hours old
- [ ] `pg_restore --list` succeeds (backup is valid)
- [ ] Restore to scratch database succeeds
- [ ] Row counts are reasonable
- [ ] Alembic version matches production
- [ ] Results documented

### 7.2 Quarterly Full Restore Test

**Frequency**: First week of each quarter (January, April, July, October)
**Duration**: 4-6 hours
**Scope**: Full environment rebuild

**Procedure**:

1. Provision a temporary Hetzner VPS
2. Follow the complete "Section 5: Full Recovery Procedure"
3. Verify all post-recovery checklist items pass
4. Measure actual RTO (must be under 4 hours)
5. Destroy temporary VPS after testing
6. Document results and update runbook if procedures have changed

**Checklist**:

- [ ] Temporary VPS provisioned
- [ ] Coolify installed successfully
- [ ] Application deployed and running
- [ ] Database restored and verified
- [ ] Redis restored and operational
- [ ] Health checks passing
- [ ] API endpoints responding correctly
- [ ] Actual RTO measured and documented
- [ ] Temporary VPS destroyed
- [ ] Runbook updated if procedures changed
- [ ] Results documented in Linear ticket

---

## Contact Escalation Matrix

| Priority | Contact | Role | Method | Response SLA |
|----------|---------|------|--------|-------------|
| **P1 (Critical)** | J. Scott Graham | POPM / Platform Owner | Phone + Slack | 15 min |
| **P2 (High)** | On-call Engineer | Platform Engineering | Slack #incidents | 30 min |
| **P3 (Medium)** | Platform Team | Engineering | Slack #platform | 4 hours |
| **P4 (Low)** | Platform Team | Engineering | Linear ticket | Next business day |

### Escalation Triggers

| Trigger | Priority | Action |
|---------|----------|--------|
| Full VPS loss | P1 | Immediately escalate to POPM, begin full recovery |
| Database corruption | P1 | Stop writes, escalate, begin DB restore |
| Backup failure (2+ consecutive) | P2 | Investigate root cause, manual backup |
| Redis failure | P2 | Restart Redis, restore from backup if needed |
| S3 partial data loss | P2 | Begin rclone restore from replica |
| Application crash (auto-recovers) | P3 | Investigate root cause, monitor |
| Single backup failure | P3 | Investigate, verify next backup succeeds |

### Communication Channels

- **Primary**: Slack `#incidents` channel
- **Secondary**: Email to `platform@rendertrust.com`
- **Status Page**: Update `status.rendertrust.com` for user-facing incidents

---

## Appendix A: Environment Variables Reference

See `.env.template` in the repository root for a complete list of required environment variables. Critical variables for DR:

- `DATABASE_URL` -- PostgreSQL connection string
- `REDIS_URL` -- Redis connection string
- `BACKUP_S3_BUCKET` -- S3 bucket for backups
- `BACKUP_S3_ACCESS_KEY` -- S3 credentials for backup operations
- `BACKUP_S3_SECRET_KEY` -- S3 credentials for backup operations
- `BACKUP_S3_ENDPOINT` -- S3-compatible endpoint URL
- `ALERT_WEBHOOK_URL` -- Webhook for backup failure alerts

## Appendix B: Related Scripts

- `scripts/backup-db.sh` -- Daily PostgreSQL backup
- `scripts/restore-db.sh` -- PostgreSQL restore from dump file or S3
- `scripts/backup-cron.sh` -- Cron wrapper for automated backups
