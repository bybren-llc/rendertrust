<!-- MIT License -- see LICENSE-MIT -->

# RenderTrust Alerting Rules

Prometheus alerting rules and Grafana notification configuration for
RenderTrust production monitoring.

## Alert Summary

| Alert                    | Condition                                          | Severity   | For Duration |
|--------------------------|----------------------------------------------------|------------|--------------|
| FleetTooFewNodes         | `fleet_nodes_total{status="healthy"} < 2`          | critical   | 5m           |
| HighErrorRate            | 5xx / total HTTP requests > 5%                     | critical   | 5m           |
| HighJobFailureRate       | Failed / total completed jobs > 10%                | warning    | 10m          |
| APILatencyHigh           | p95 request duration > 5s                          | warning    | 5m           |
| NoWebSocketConnections   | `active_websocket_connections == 0`                | warning    | 10m          |

## Notification Routing

| Severity   | Channels              |
|------------|-----------------------|
| critical   | Discord + Email       |
| warning    | Discord only          |

## Setup

### 1. Configure Discord Webhook

1. In your Discord server, go to **Server Settings > Integrations > Webhooks**.
2. Click **New Webhook**, choose the target channel, and copy the URL.
3. Set the environment variable before starting Grafana:

```bash
export DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
```

### 2. Configure Email (SMTP)

Set the following environment variables for Grafana's SMTP integration:

```bash
export ALERT_EMAIL_ADDRESSES="ops-team@example.com"
```

Also ensure Grafana's `grafana.ini` (or `GF_SMTP_*` env vars) has SMTP
configured:

```ini
[smtp]
enabled = true
host = smtp.example.com:587
user = alerts@example.com
password = ****
from_address = alerts@example.com
```

### 3. Prometheus Rule Files

The `prometheus-rules.yml` file is loaded by Prometheus via the `rule_files`
directive in `ci/grafana/prometheus.yml`:

```yaml
rule_files:
  - "/etc/prometheus/alerts/*.yml"
```

Mount the alerts directory into the Prometheus container at
`/etc/prometheus/alerts/`.

### 4. Grafana Notification Provisioning

Copy `grafana-contact-points.yml` into Grafana's provisioning directory:

```
/etc/grafana/provisioning/alerting/grafana-contact-points.yml
```

Or mount it via Docker volume in your `docker-compose.yml`.

## Adding Custom Alerts

To add a new alert rule:

1. Edit `prometheus-rules.yml` and add a new entry under `rules:`.
2. Use metrics from `core/metrics.py` (see comments at the top of the file).
3. Follow the existing pattern:

```yaml
- alert: YourAlertName
  expr: your_metric_expression > threshold
  for: 5m
  labels:
    severity: warning   # or critical
  annotations:
    summary: "Human-readable summary"
    description: "Detailed description with {{ $value }} template."
```

4. Reload Prometheus (`POST /-/reload`) or restart the container.

## Silencing / Muting Alerts

### Via Grafana UI

1. Navigate to **Alerting > Silences** in the Grafana sidebar.
2. Click **Create Silence**.
3. Add matchers (e.g., `alertname = FleetTooFewNodes`).
4. Set the duration and add a comment explaining the reason.
5. Click **Submit**.

### Via Grafana API

```bash
curl -X POST http://localhost:3000/api/alertmanager/grafana/api/v2/silences \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $GRAFANA_API_KEY" \
  -d '{
    "matchers": [{"name": "alertname", "value": "FleetTooFewNodes", "isRegex": false}],
    "startsAt": "2026-01-01T00:00:00Z",
    "endsAt": "2026-01-01T06:00:00Z",
    "createdBy": "ops-team",
    "comment": "Planned maintenance window"
  }'
```

### Via Prometheus Alertmanager (if using standalone)

```bash
amtool silence add alertname=FleetTooFewNodes --duration=2h --comment="Maintenance"
```

## File Reference

| File                         | Purpose                                       |
|------------------------------|-----------------------------------------------|
| `prometheus-rules.yml`       | Prometheus alerting rule definitions           |
| `grafana-contact-points.yml` | Grafana contact points and notification policy |
| `README.md`                  | This documentation                            |
