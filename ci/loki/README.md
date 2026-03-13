# MIT License -- see LICENSE-MIT

# Loki Logging Stack for RenderTrust

Structured log aggregation using **Promtail** (collector) + **Loki** (storage) + **Grafana** (visualization).

RenderTrust uses [structlog](https://www.structlog.org/) with JSON rendering. This stack collects those JSON logs from Docker containers, indexes them in Loki, and makes them searchable through Grafana.

## Architecture

```
Docker containers (structlog JSON on stdout)
        |
    Promtail  (scrapes via Docker socket, parses JSON fields)
        |
      Loki    (indexes and stores log streams, 30-day retention)
        |
     Grafana  (query and visualize with LogQL)
```

## Prerequisites

- Docker and Docker Compose v2+
- The application containers must be running on the `rendertrust-net` Docker network

## Quick Start

1. **Create the shared network** (if it does not already exist):

   ```bash
   docker network create rendertrust-net
   ```

2. **Start the logging stack**:

   ```bash
   docker compose -f ci/loki/docker-compose.loki.yml up -d
   ```

3. **Start the application** (ensure it joins the same network):

   ```bash
   docker compose up -d
   ```

   If your application compose file does not already reference the `rendertrust-net` external network, add this to it:

   ```yaml
   networks:
     rendertrust-net:
       external: true
   ```

   And attach the relevant services to that network.

4. **Open Grafana**: Navigate to [http://localhost:3000](http://localhost:3000)
   - Default credentials: `admin` / `rendertrust`
   - The Loki datasource is auto-provisioned

5. **Explore logs**: Go to **Explore** (compass icon in the sidebar), select the **Loki** datasource, and run a query.

## Common LogQL Queries

### View all logs from a specific service

```logql
{service="core"}
```

### Filter by log level

```logql
{service="core"} | json | level="error"
```

### Filter by request ID (for request tracing)

```logql
{request_id="abc-123-def"}
```

Or search across all services:

```logql
{compose_project="rendertrust"} | json | request_id="abc-123-def"
```

### Filter by event name

```logql
{service="core"} | json | event="request_started"
```

### Search log message text

```logql
{service="core"} |= "payment failed"
```

### Rate of errors over time

```logql
rate({service="core"} | json | level="error" [5m])
```

### Top 10 most frequent events

```logql
topk(10, sum by (event)(rate({service="core"} | json [5m])))
```

### Logs from all RenderTrust containers

```logql
{compose_project="rendertrust"}
```

## Stopping the Stack

```bash
docker compose -f ci/loki/docker-compose.loki.yml down
```

To also remove stored data:

```bash
docker compose -f ci/loki/docker-compose.loki.yml down -v
```

## Production Integration

For production (Coolify on Hetzner), this stack can be deployed alongside the main application:

1. **Network**: The `rendertrust-net` external network lets the logging stack and the application stack communicate without merging compose files.

2. **Retention**: Loki is configured for 30-day retention with automatic compaction. Adjust `retention_period` in `loki-config.yml` for production needs.

3. **Storage**: In production, consider replacing the local filesystem backend with S3-compatible object storage for durability.

4. **Grafana dashboards**: Import or create dashboards in Grafana and save them to a provisioning directory for persistence across restarts.

5. **Alerting**: Grafana supports alerting on LogQL queries. Configure alert rules for error rate thresholds and critical events.

## File Overview

| File | Purpose |
|------|---------|
| `loki-config.yml` | Loki server configuration (storage, retention, limits) |
| `promtail-config.yml` | Promtail log collection and JSON parsing pipeline |
| `docker-compose.loki.yml` | Docker Compose stack definition |
| `grafana-datasources.yml` | Grafana auto-provisioning for Loki datasource |
| `README.md` | This file |

## Troubleshooting

- **Promtail not collecting logs**: Ensure the Docker socket is accessible (`/var/run/docker.sock`) and the containers have compose labels.
- **Loki not ready**: Check `docker logs rendertrust-loki` for startup errors. The healthcheck waits for `/ready`.
- **No data in Grafana**: Verify that Promtail is connected to Loki (`docker logs rendertrust-promtail`) and that the time range in Grafana covers recent log entries.
- **Permission errors**: On SELinux systems, you may need to add `:z` to volume mounts for the Docker socket.
