# Database Migration Runbook

> MIT License -- see LICENSE-MIT

This runbook covers all database migration operations for RenderTrust,
including automatic migrations on deploy, manual migration procedures,
rollback strategies, and emergency recovery.

Related tickets: REN-118 (auto-migration on deploy), REN-115 (Coolify
entrypoint), REN-117 (production Docker Compose).

---

## Table of Contents

1. [How Migrations Run Automatically](#how-migrations-run-automatically)
2. [Checking Current Migration Status](#checking-current-migration-status)
3. [Running Migrations Manually](#running-migrations-manually)
4. [Rolling Back Migrations](#rolling-back-migrations)
5. [Creating New Migrations](#creating-new-migrations)
6. [Troubleshooting](#troubleshooting)
7. [Emergency Procedures](#emergency-procedures)
8. [Best Practices](#best-practices)

---

## How Migrations Run Automatically

RenderTrust runs database migrations automatically during deployment via
two complementary mechanisms:

### 1. Entrypoint (ci/coolify/entrypoint.sh)

The production Docker image uses `ci/coolify/entrypoint.sh` as its
`ENTRYPOINT`. On every container start, the entrypoint:

1. Waits for PostgreSQL to accept TCP connections (up to 60 seconds).
2. Runs `alembic upgrade head` to apply all pending migrations.
3. Starts the uvicorn application server.

If the migration step fails, the entrypoint exits with a non-zero status
and the container does not start. This prevents the application from
running against an incompatible database schema.

### 2. Deploy Script (ci/deploy.sh)

The deploy script provides an additional safety layer. Before restarting
the application, it runs migrations in an **ephemeral container**:

```bash
docker compose run --rm --no-deps app alembic upgrade head
```

This ensures that migration failure does not disrupt the currently
running application. The deploy script only proceeds to restart
services after migrations succeed.

### 3. GitHub Actions Workflow

The `rendertrust-deploy.yml` workflow runs migrations as a separate job
between the test and deploy stages. This provides CI-level validation
that migrations are safe before any production changes occur.

---

## Checking Current Migration Status

### View the current Alembic revision

```bash
# Via docker compose (recommended for production)
docker compose -f docker-compose.prod.yml exec app alembic current

# In a local development environment
alembic current
```

### View migration history

```bash
# Show all revisions in order
alembic history --verbose

# Show only pending migrations (not yet applied)
alembic history --indicate-current
```

### Verify the database matches the latest migration

```bash
# This should output the head revision hash
docker compose -f docker-compose.prod.yml exec app alembic heads

# Compare with current
docker compose -f docker-compose.prod.yml exec app alembic current
```

If `current` and `heads` show different revisions, there are unapplied
migrations.

---

## Running Migrations Manually

### Apply all pending migrations

```bash
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
```

### Apply a specific number of migrations

```bash
# Apply the next 1 migration only
docker compose -f docker-compose.prod.yml exec app alembic upgrade +1

# Apply the next 2 migrations
docker compose -f docker-compose.prod.yml exec app alembic upgrade +2
```

### Apply up to a specific revision

```bash
docker compose -f docker-compose.prod.yml exec app alembic upgrade <revision_hash>
```

### Using the deploy script

```bash
# Run only migrations (will also restart the app afterward)
./ci/deploy.sh

# Skip the image pull, just migrate and restart
./ci/deploy.sh --build
```

---

## Rolling Back Migrations

### Roll back one migration

```bash
docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
```

### Roll back to a specific revision

```bash
# First, check the revision you want to roll back to
docker compose -f docker-compose.prod.yml exec app alembic history

# Then downgrade to that specific revision
docker compose -f docker-compose.prod.yml exec app alembic downgrade <revision_hash>
```

### Roll back all migrations (DANGEROUS)

```bash
# This removes ALL tables. Only use in development.
docker compose -f docker-compose.prod.yml exec app alembic downgrade base
```

### Using the deploy script for application rollback

The deploy script can roll back the Docker image (not the database
migration) to the previous version:

```bash
./ci/deploy.sh --rollback
```

This restores the previously running container image. Note that you may
also need to roll back the database migration separately if the previous
application version requires an older schema.

### Full rollback procedure (application + database)

1. Roll back the database migration first:

   ```bash
   docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
   ```

2. Roll back the application:

   ```bash
   ./ci/deploy.sh --rollback
   ```

3. Verify the application is healthy:

   ```bash
   curl -f http://localhost:8000/health
   ```

---

## Creating New Migrations

### Auto-generate a migration from model changes

```bash
# In a development environment with database access
alembic revision --autogenerate -m "add user preferences table"
```

### Create an empty migration (for manual SQL)

```bash
alembic revision -m "backfill user display names"
```

### Migration file conventions

- Place migrations in `alembic/versions/`.
- Use descriptive messages: `"add index on jobs.status"`, not `"update"`.
- Always include both `upgrade()` and `downgrade()` functions.
- Test both directions locally before committing.

### Commit format

```bash
git add alembic/versions/
git commit -m "feat(db): add user preferences table [REN-XXX]"
```

---

## Troubleshooting

### Migration lock (another process is running migrations)

**Symptom**: Migration hangs or reports "could not obtain lock".

**Cause**: Another Alembic process or database client holds an advisory
lock on the migration table.

**Resolution**:

1. Check for running migration processes:

   ```bash
   docker compose -f docker-compose.prod.yml exec db \
     psql -U rendertrust -d rendertrust -c \
     "SELECT pid, state, query FROM pg_stat_activity WHERE query LIKE '%alembic%';"
   ```

2. If a stale lock exists, terminate the blocking session:

   ```bash
   docker compose -f docker-compose.prod.yml exec db \
     psql -U rendertrust -d rendertrust -c \
     "SELECT pg_terminate_backend(<pid>);"
   ```

3. Retry the migration.

### Migration fails with "relation already exists"

**Cause**: The migration was partially applied, or the schema was
modified outside of Alembic.

**Resolution**:

1. Check the current Alembic version:

   ```bash
   docker compose -f docker-compose.prod.yml exec app alembic current
   ```

2. If the version table is out of sync, stamp the database to the
   correct revision without running migrations:

   ```bash
   docker compose -f docker-compose.prod.yml exec app alembic stamp <revision>
   ```

3. Then run the remaining migrations:

   ```bash
   docker compose -f docker-compose.prod.yml exec app alembic upgrade head
   ```

### Migration fails with "column does not exist" or data error

**Cause**: The migration references a column or data state that does
not match the current database.

**Resolution**:

1. Do NOT force the migration. Investigate the discrepancy.
2. Check if the database was manually altered:

   ```bash
   docker compose -f docker-compose.prod.yml exec db \
     psql -U rendertrust -d rendertrust -c "\dt"
   ```

3. Fix the migration script or create a corrective migration.
4. Never edit a migration that has already been applied to production.
   Create a new migration instead.

### Alembic version table missing

**Cause**: First deploy, or the database was recreated without running
migrations.

**Resolution**: Simply run `alembic upgrade head`. Alembic will create
the `alembic_version` table automatically.

### Connection refused to database

**Cause**: PostgreSQL is not running or not accessible from the app
container.

**Resolution**:

1. Check that the database container is running:

   ```bash
   docker compose -f docker-compose.prod.yml ps db
   ```

2. Check database logs:

   ```bash
   docker compose -f docker-compose.prod.yml logs db --tail=20
   ```

3. Verify the `DATABASE_URL` environment variable is correct.
4. If using the entrypoint, it will retry for up to 60 seconds. If it
   still fails, check network connectivity between containers.

---

## Emergency Procedures

### Scenario: Bad migration deployed to production

**Immediate response** (within minutes):

1. **Do NOT panic.** The application may still be running on the old
   container if the deploy script detected the failure.

2. Check application health:

   ```bash
   curl -f http://localhost:8000/health
   ```

3. If the app is down, roll back the migration:

   ```bash
   docker compose -f docker-compose.prod.yml exec app alembic downgrade -1
   ```

4. If the app container is not running, start a temporary one:

   ```bash
   docker compose -f docker-compose.prod.yml run --rm app alembic downgrade -1
   ```

5. Restart the previous application version:

   ```bash
   ./ci/deploy.sh --rollback
   ```

### Scenario: Data loss from a migration

**Immediate response**:

1. **Stop all writes** to the affected table if possible.
2. Check if the migration has a proper `downgrade()` that restores data.
   Most `DROP COLUMN` downgrades cannot restore data.
3. If data is lost, restore from the most recent database backup:

   ```bash
   # Stop the application
   docker compose -f docker-compose.prod.yml stop app

   # Restore from backup (example using pg_restore)
   docker compose -f docker-compose.prod.yml exec db \
     pg_restore -U rendertrust -d rendertrust --clean /backups/latest.dump

   # Re-apply any migrations that should be active
   docker compose -f docker-compose.prod.yml run --rm app alembic upgrade head

   # Restart the application
   docker compose -f docker-compose.prod.yml start app
   ```

4. File an incident report and update the migration to be non-destructive.

### Scenario: Database completely unreachable

1. Check host-level resources (disk, memory, connections):

   ```bash
   docker compose -f docker-compose.prod.yml exec db \
     psql -U rendertrust -c "SELECT count(*) FROM pg_stat_activity;"
   ```

2. If the database container is OOM-killed, increase memory limits in
   `docker-compose.prod.yml` and restart:

   ```bash
   docker compose -f docker-compose.prod.yml up -d db
   ```

3. Wait for the database health check to pass, then restart the app:

   ```bash
   docker compose -f docker-compose.prod.yml up -d app
   ```

---

## Best Practices

### Writing safe migrations

- **Always provide a downgrade path.** Every `upgrade()` should have a
  corresponding `downgrade()` that reverses the change.
- **Avoid destructive operations in production.** Use `ADD COLUMN` with
  a default value instead of recreating tables. Never use `DROP TABLE`
  unless the table is confirmed unused.
- **Make migrations backwards-compatible.** The old application version
  should still work with the new schema during rolling deployments.
  This means: add columns as nullable first, deploy code that writes
  to the new column, then add the NOT NULL constraint in a separate
  migration.
- **Keep migrations small.** One logical change per migration file.
  This makes rollbacks precise.
- **Test both directions locally.**

  ```bash
  alembic upgrade head
  alembic downgrade -1
  alembic upgrade head
  ```

### Deployment safety

- **Always back up the database before deploying migrations** that alter
  existing tables or remove columns.
- **Use the deploy script** (`ci/deploy.sh`) rather than running
  migrations and restarts manually. It handles failure detection and
  rollback automatically.
- **Monitor the application** after deploy. Check logs and health
  endpoint for at least 5 minutes after a migration-bearing deploy.
- **Use staging first.** The GitHub Actions workflow supports staging
  and production environments. Always deploy to staging before
  production.
