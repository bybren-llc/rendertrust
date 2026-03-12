<!-- MIT License -- see LICENSE-MIT -->

# Cloudflare DNS and Tunnel Setup Guide

> RenderTrust production deployment on Hetzner VPS via Coolify,
> secured by Cloudflare Tunnel (no open inbound ports).

**Related tickets**: REN-115 (Coolify), REN-116 (this guide), REN-120 (Prometheus)

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1 -- Create the Tunnel](#step-1----create-the-tunnel)
3. [Step 2 -- Copy Credentials to Server](#step-2----copy-credentials-to-server)
4. [Step 3 -- Configure DNS Records](#step-3----configure-dns-records)
5. [Step 4 -- SSL/TLS Settings](#step-4----ssltls-settings)
6. [Step 5 -- WAF Configuration](#step-5----waf-configuration)
7. [Step 6 -- Page Rules and Cache Settings](#step-6----page-rules-and-cache-settings)
8. [Step 7 -- Start the Cloudflared Service](#step-7----start-the-cloudflared-service)
9. [DNS Records Reference](#dns-records-reference)
10. [Troubleshooting](#troubleshooting)
11. [Security Hardening Checklist](#security-hardening-checklist)

---

## Prerequisites

Before starting, ensure you have:

- [ ] A Cloudflare account (Free plan is sufficient for tunnels; Pro recommended for WAF)
- [ ] The `rendertrust.com` domain added to your Cloudflare account with nameservers updated
- [ ] `cloudflared` CLI installed locally (`brew install cloudflared` or [download](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/))
- [ ] SSH access to the Hetzner VPS where Coolify is running (REN-115)
- [ ] Docker and Docker Compose installed on the VPS
- [ ] The `rendertrust-net` Docker network created (`docker network create rendertrust-net`)
- [ ] The Coolify stack running (`ci/coolify/docker-compose.coolify.yml`)

---

## Step 1 -- Create the Tunnel

On your **local machine** (not the server), authenticate with Cloudflare and create the tunnel.

```bash
# Authenticate with Cloudflare (opens browser)
cloudflared tunnel login

# Create the tunnel
cloudflared tunnel create rendertrust
```

This outputs a **Tunnel ID** (UUID) and creates a credentials file at:

```
~/.cloudflared/<TUNNEL_ID>.json
```

Save the Tunnel ID -- you will need it in subsequent steps.

### Alternative: Token-Based Authentication

If you prefer not to manage credential files, you can create a tunnel via the
Cloudflare Zero Trust dashboard and obtain a **TUNNEL_TOKEN** instead:

1. Go to **Cloudflare Zero Trust** > **Access** > **Tunnels**
2. Click **Create a tunnel**
3. Name it `rendertrust`
4. Copy the provided token

Token-based auth is simpler for Coolify deployments since you only need to set
a single environment variable.

---

## Step 2 -- Copy Credentials to Server

If using **credential file** authentication (not token-based):

```bash
# Create credentials directory on the server
ssh user@<HETZNER_IP> "mkdir -p /opt/rendertrust/cloudflare/credentials"

# Copy the credentials JSON
scp ~/.cloudflared/<TUNNEL_ID>.json \
  user@<HETZNER_IP>:/opt/rendertrust/cloudflare/credentials/<TUNNEL_ID>.json

# Lock down permissions (credentials contain the tunnel secret)
ssh user@<HETZNER_IP> "chmod 600 /opt/rendertrust/cloudflare/credentials/<TUNNEL_ID>.json"
```

Copy the tunnel configuration files to the server:

```bash
# Copy config files
scp ci/cloudflare/tunnel-config.yml \
  user@<HETZNER_IP>:/opt/rendertrust/cloudflare/tunnel-config.yml

scp ci/cloudflare/docker-compose.tunnel.yml \
  user@<HETZNER_IP>:/opt/rendertrust/cloudflare/docker-compose.tunnel.yml
```

Edit `tunnel-config.yml` on the server to replace `<TUNNEL_ID>` with your
actual tunnel UUID:

```bash
ssh user@<HETZNER_IP> \
  "sed -i 's/<TUNNEL_ID>/YOUR-ACTUAL-UUID/g' /opt/rendertrust/cloudflare/tunnel-config.yml"
```

---

## Step 3 -- Configure DNS Records

Each hostname in `tunnel-config.yml` needs a CNAME record pointing to the
tunnel. You can create these via the CLI or the Cloudflare dashboard.

### Via CLI

```bash
# API subdomain
cloudflared tunnel route dns rendertrust api.rendertrust.com

# Web app subdomain
cloudflared tunnel route dns rendertrust app.rendertrust.com

# Grafana (internal monitoring)
cloudflared tunnel route dns rendertrust grafana.rendertrust.com

# Root domain (optional -- redirect to app or marketing site)
cloudflared tunnel route dns rendertrust rendertrust.com
```

### Via Cloudflare Dashboard

1. Go to **DNS** > **Records** for `rendertrust.com`
2. Add CNAME records as listed in the [DNS Records Reference](#dns-records-reference) below
3. Ensure the **Proxy** toggle (orange cloud) is **ON** for all records

---

## Step 4 -- SSL/TLS Settings

Configure SSL/TLS in the Cloudflare dashboard:

1. Go to **SSL/TLS** > **Overview**
2. Set encryption mode to **Full (strict)**
   - This encrypts traffic between visitors and Cloudflare, AND between
     Cloudflare and your tunnel (even though the tunnel itself is encrypted,
     Full strict ensures end-to-end certificate validation)
3. Go to **SSL/TLS** > **Edge Certificates**
   - Enable **Always Use HTTPS**
   - Set **Minimum TLS Version** to **TLS 1.2**
   - Enable **TLS 1.3**
   - Enable **Automatic HTTPS Rewrites**
4. Go to **SSL/TLS** > **Origin Server**
   - The tunnel handles origin connectivity; no origin certificate needed
   - If you later expose services directly (not via tunnel), generate an
     origin certificate here

### HSTS Configuration

Under **SSL/TLS** > **Edge Certificates** > **HTTP Strict Transport Security (HSTS)**:

- Enable HSTS
- Max-Age: 6 months (15768000 seconds)
- Include subdomains: Yes
- Preload: Yes (after confirming all subdomains support HTTPS)
- No-Sniff: Yes

---

## Step 5 -- WAF Configuration

### Enable Managed Rulesets

1. Go to **Security** > **WAF** > **Managed Rules**
2. Enable the **Cloudflare Managed Ruleset** (OWASP Core Rule Set)
3. Set sensitivity to **Medium** initially (tune after observing false positives)
4. Enable the **Cloudflare OWASP Core Rule Set**

### Import Custom Rules

The file `waf-rules.json` contains custom rules for RenderTrust. Import them
via the Cloudflare API or recreate them manually in the dashboard:

```bash
# Import via API (requires API token with Firewall:Edit permission)
curl -X POST \
  "https://api.cloudflare.com/client/v4/zones/<ZONE_ID>/firewall/rules" \
  -H "Authorization: Bearer <API_TOKEN>" \
  -H "Content-Type: application/json" \
  -d @ci/cloudflare/waf-rules.json
```

### Custom Rules Summary

| Rule | Action | Priority | Description |
|------|--------|----------|-------------|
| Stripe webhook allow | Skip | 1 | Bypass rate limits for Stripe IPs on webhook path |
| API rate limit | Rate Limit | 10 | 100 req/min per IP on `/api/*` |
| Auth rate limit | Rate Limit | 11 | 20 req/min per IP on `/api/v1/auth/*` |
| SQL injection block | Block | 20 | Block common SQLi patterns in URL |
| XSS block | Block | 21 | Block `<script>`, `javascript:`, etc. in URL |
| Path traversal block | Block | 22 | Block `../` and encoded variants |
| Suspicious UA challenge | Challenge | 30 | Challenge empty or known-malicious user agents |

### Rate Limiting Notes

- The general API rate limit (100 req/min) is a starting point. Monitor
  `429` response rates after launch and adjust.
- Auth endpoints have a stricter limit (20 req/min) to mitigate brute force.
- Stripe webhooks bypass rate limiting to avoid dropped payment events.

---

## Step 6 -- Page Rules and Cache Settings

### API Endpoints (No Cache)

1. Go to **Rules** > **Page Rules**
2. Create rule: `api.rendertrust.com/*`
   - Cache Level: **Bypass**
   - Disable Performance (optional -- API responses should not be minified)
   - Security Level: **High**

### Static Assets (Aggressive Cache)

1. Create rule: `app.rendertrust.com/static/*`
   - Cache Level: **Cache Everything**
   - Edge Cache TTL: **1 month**
   - Browser Cache TTL: **1 week**

### Grafana Dashboard

1. Create rule: `grafana.rendertrust.com/*`
   - Cache Level: **Bypass**
   - Security Level: **I'm Under Attack** (or protect with Cloudflare Access)

### Cache Configuration via Dashboard

For finer control, use **Caching** > **Configuration**:

- Browser Cache TTL: **Respect Existing Headers** (FastAPI sets Cache-Control)
- Crawler Hints: Enabled
- Always Online: Enabled (serves stale content if origin is down)

---

## Step 7 -- Start the Cloudflared Service

On the Hetzner VPS:

```bash
cd /opt/rendertrust/cloudflare

# If using token-based auth, set the token
export TUNNEL_TOKEN="your-tunnel-token-here"

# Start the tunnel
docker compose -f docker-compose.tunnel.yml up -d

# Verify it is running and healthy
docker compose -f docker-compose.tunnel.yml ps
docker compose -f docker-compose.tunnel.yml logs -f cloudflared
```

### Verify Tunnel Connectivity

```bash
# Check tunnel status via cloudflared metrics
curl -s http://localhost:2000/ready
# Expected: {"readyConnections":4}

# Test from outside (after DNS propagation)
curl -I https://api.rendertrust.com/health
# Expected: HTTP/2 200 with cf-ray header
```

### Start on Boot

The `restart: unless-stopped` policy in the compose file ensures the tunnel
restarts automatically after a VPS reboot, as long as Docker is enabled:

```bash
sudo systemctl enable docker
```

---

## DNS Records Reference

| Record Type | Name | Content | Proxy | Notes |
|-------------|------|---------|-------|-------|
| CNAME | `rendertrust.com` | `<TUNNEL_ID>.cfargotunnel.com` | ON | Root domain (optional redirect) |
| CNAME | `api` | `<TUNNEL_ID>.cfargotunnel.com` | ON | FastAPI gateway (port 8000) |
| CNAME | `app` | `<TUNNEL_ID>.cfargotunnel.com` | ON | Web application (port 3000) |
| CNAME | `grafana` | `<TUNNEL_ID>.cfargotunnel.com` | ON | Monitoring (port 3001, restricted) |
| TXT | `_dmarc` | `v=DMARC1; p=reject; rua=mailto:admin@rendertrust.com` | -- | Email spoofing protection |
| TXT | `@` | `v=spf1 -all` | -- | No email sent from this domain |
| MX | `@` | (none or external provider) | -- | Configure if using email |

> **Note**: Replace `<TUNNEL_ID>` with your actual tunnel UUID. The `.cfargotunnel.com`
> suffix is Cloudflare's tunnel routing domain.

---

## Troubleshooting

### Tunnel Not Connecting

```bash
# Check cloudflared container logs
docker compose -f docker-compose.tunnel.yml logs cloudflared

# Common causes:
# - Invalid TUNNEL_TOKEN or credentials file
# - Incorrect tunnel name in config
# - DNS not propagated yet (wait 5 minutes, then check)
# - Firewall blocking outbound connections (cloudflared needs outbound 443)
```

### 502 Bad Gateway

The tunnel is connected but the origin service is unreachable:

```bash
# Verify the target service is running
curl -s http://localhost:8000/health

# Check if the Coolify stack is healthy
docker compose -f /path/to/docker-compose.coolify.yml ps

# Ensure cloudflared is on the same Docker network
docker network inspect rendertrust-net | grep cloudflared
```

### DNS Resolution Issues

```bash
# Check DNS propagation
dig api.rendertrust.com CNAME +short
# Expected: <TUNNEL_ID>.cfargotunnel.com.

# If stale, flush DNS cache or wait for TTL expiry
# Check Cloudflare dashboard for DNS record status
```

### Certificate Errors

- Ensure SSL/TLS mode is **Full (strict)**, not **Flexible**
- Cloudflare provides edge certificates automatically for proxied records
- If you see mixed content warnings, enable **Automatic HTTPS Rewrites**

### Rate Limiting Too Aggressive

```bash
# Check Cloudflare analytics for 429 responses
# Dashboard: Security > Events

# To temporarily increase limits:
# 1. Edit waf-rules.json
# 2. Update the rule via API or dashboard
# 3. Monitor for 24 hours before making permanent
```

### Cloudflare Access (Zero Trust) for Grafana

To restrict Grafana access to team members only:

1. Go to **Cloudflare Zero Trust** > **Access** > **Applications**
2. Add application: `grafana.rendertrust.com`
3. Set policy: Allow only specific email addresses or identity provider groups
4. This adds a login page before the Grafana dashboard

---

## Security Hardening Checklist

Complete these items before going to production:

### Cloudflare Settings

- [ ] SSL/TLS mode set to **Full (strict)**
- [ ] HSTS enabled with preload
- [ ] Minimum TLS version set to **1.2**
- [ ] TLS 1.3 enabled
- [ ] Always Use HTTPS enabled
- [ ] Automatic HTTPS Rewrites enabled
- [ ] WAF Managed Rules enabled (OWASP ruleset)
- [ ] Custom WAF rules deployed (waf-rules.json)
- [ ] Rate limiting active on API endpoints
- [ ] Stricter rate limiting on auth endpoints
- [ ] Bot Fight Mode enabled (Security > Bots)
- [ ] Browser Integrity Check enabled

### DNS Security

- [ ] All DNS records proxied (orange cloud ON)
- [ ] SPF record set (`v=spf1 -all` if no email)
- [ ] DMARC record set (`v=DMARC1; p=reject`)
- [ ] No DNS records expose the origin IP

### Tunnel Security

- [ ] Tunnel credentials file permissions set to 600
- [ ] TUNNEL_TOKEN stored securely (Coolify secrets, not in git)
- [ ] `noTLSVerify` only used for localhost connections (never for external origins)
- [ ] Catch-all ingress rule returns 404 (no open proxy)

### VPS Firewall

- [ ] No inbound ports open except SSH (port 22, key-only)
- [ ] UFW or iptables configured to block all other inbound traffic
- [ ] cloudflared only makes outbound connections (port 443)
- [ ] SSH restricted to known IPs or behind Cloudflare Access

### Application Security

- [ ] Stripe webhook endpoint validates signatures (core/billing/)
- [ ] CORS headers restrict origins to `*.rendertrust.com`
- [ ] API authentication enforced on all non-public endpoints
- [ ] Request-ID correlation enabled (REN-71)
- [ ] Structured logging enabled (REN-119)

### Monitoring

- [ ] Grafana protected by Cloudflare Access (Zero Trust)
- [ ] Cloudflare analytics monitored for anomalies
- [ ] Tunnel health checked via `/ready` endpoint
- [ ] Alerting configured for tunnel disconnections
