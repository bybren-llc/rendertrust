# User Guide — Creator (Job Submitter)

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Who Is This For?

This guide is for **creators** — users who submit computational jobs (rendering, AI inference, data processing) to the RenderTrust network and download results. You'll use the **Creator Desktop App** (Electron) or the **Python SDK**.

---

## Getting Started

### 1. Install the Desktop App

Download the RenderTrust Creator app for your platform:

- **macOS**: `RenderTrust-1.0.0-alpha.dmg`
- **Windows**: `RenderTrust-1.0.0-alpha-setup.exe`
- **Linux**: `RenderTrust-1.0.0-alpha.AppImage`

Or build from source:
```bash
cd frontend/
npm install
npm run build
npm run electron:build
```

### 2. Create an Account

1. Launch the Creator app
2. Click **"Create Account"** on the login screen
3. Enter your email, name, and password (minimum 8 characters)
4. Click **Register**
5. You'll be logged in automatically

### 3. Purchase Credits

Before submitting jobs, you need credits:

1. Navigate to **Credits** in the sidebar
2. View your current balance in the **Available Balance** card
3. Under **Buy Credits**, choose a package:
   - 100 credits — $10.00 ($0.100/credit)
   - 500 credits — $40.00 ($0.080/credit)
   - 1,000 credits — $70.00 ($0.070/credit)
4. Click **Buy Now**
5. Complete payment on the Stripe checkout page
6. Credits appear in your balance after payment confirmation

---

## Submitting Jobs

### From the Desktop App

1. Navigate to **Jobs** in the sidebar
2. Click **Submit Job**
3. Fill in the form:
   - **Job Type**: Select from render, inference, or generic
   - **Payload**: Enter a reference URI (S3/IPFS) or paste JSON directly
   - **Priority**: Low, Normal, or High
   - **GPU Required**: Toggle on if your job needs GPU
4. Click **Submit**
5. On success, you'll see the assigned job ID and node

### From the Python SDK

```python
from rendertrust import RenderTrustClient

client = RenderTrustClient(base_url="https://api.rendertrust.com")
client.login("you@example.com", "your-password")

# Submit a job
result = client.submit_job(
    job_type="render",
    payload={"ref": "s3://your-bucket/scene.blend"}
)
print(f"Job {result['job_id']} dispatched to node {result['node_id']}")
```

### From the API

```bash
curl -X POST https://api.rendertrust.com/api/v1/jobs/dispatch \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"job_type": "render", "payload_ref": "s3://bucket/scene.blend"}'
```

---

## Monitoring Jobs

### Job Statuses

| Status | Icon | Meaning |
|--------|------|---------|
| **QUEUED** | Yellow | Job created, waiting for dispatch |
| **DISPATCHED** | Blue | Assigned to a node, in transit |
| **RUNNING** | Blue (animated) | Node is actively executing |
| **COMPLETED** | Green | Finished, result available |
| **FAILED** | Red | Execution failed (may auto-retry) |

### In the Desktop App

1. Navigate to **Jobs** in the sidebar
2. The job list shows all your jobs with status badges
3. Use the **status filter** buttons to filter by state
4. Click a job row to see full details
5. Active jobs auto-refresh every 5 seconds

### In the SDK

```python
# Check job status
job = client.get_job("job-uuid")
print(f"Status: {job['status']}")

# List all running jobs
running = client.list_jobs(status="RUNNING")
for job in running:
    print(f"{job['id']}: {job['status']}")
```

---

## Downloading Results

### From the Desktop App

1. Open a **COMPLETED** job
2. Click **Download Result**
3. The file saves to your default downloads folder

### From the SDK

```python
# Download result to a file
filepath = client.download_result("job-uuid", output_path="output.png")
print(f"Saved to {filepath}")
```

### From the API

```bash
# Get presigned download URL
curl https://api.rendertrust.com/api/v1/jobs/JOB_ID/result \
  -H "Authorization: Bearer YOUR_TOKEN"

# Response: { "download_url": "https://...", "expires_in": 3600 }
# Then download directly from the URL (no auth needed)
```

---

## Cancelling Jobs

You can cancel jobs that are in **QUEUED** or **DISPATCHED** state:

### Desktop App
1. Open the job
2. Click **Cancel** button (only visible for cancellable jobs)

### SDK
```python
client.cancel_job("job-uuid")
```

### API
```bash
curl -X POST https://api.rendertrust.com/api/v1/jobs/JOB_ID/cancel \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## Managing Credits

### Viewing Balance

The **Credits** page shows:
- **Available Balance** — Your current credit count
- **Usage Chart** — 7-day rolling credit consumption graph
- **Transaction History** — All credit movements with type badges:
  - Green "purchase" — Credits bought via Stripe
  - Red "deduction" — Credits consumed by job execution
  - Blue "refund" — Credits returned (e.g., failed job refund)

### Understanding Credit Costs

| Job Type | Credits Per Job |
|----------|----------------|
| Render | 10 |
| AI Inference | 5 |
| CPU Benchmark | 1 |
| Echo (test) | 0 (free) |

Costs are deducted when jobs **complete** (not when submitted). Failed jobs that exhaust retries may be refunded.

### Insufficient Credits

If you try to submit a job without enough credits:
- The app shows a warning message
- The API returns `402 Payment Required`
- Navigate to Credits and purchase more

---

## Verifying Transactions (Blockchain)

Every credit transaction is anchored on-chain for transparency:

1. View your **Transaction History**
2. Note the transaction ID
3. Use the API to verify:

```bash
# Get Merkle proof
curl https://api.rendertrust.com/api/v1/ledger/ENTRY_ID/proof \
  -H "Authorization: Bearer YOUR_TOKEN"

# Verify against on-chain anchor
curl https://api.rendertrust.com/api/v1/ledger/ENTRY_ID/verify \
  -H "Authorization: Bearer YOUR_TOKEN"
# Response: { "verified": true, ... }
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **"No healthy nodes"** on dispatch | No nodes available for your job type. Try again later or contact support. |
| **Job stuck in DISPATCHED** | Node may be processing. Jobs auto-timeout after 5 minutes. |
| **Job FAILED** | Check error message. Jobs auto-retry up to 3 times. |
| **Credits not appearing after purchase** | Allow 30 seconds for webhook processing. Refresh the page. |
| **Login fails** | Check email/password. Too many attempts trigger rate limiting (wait 1 minute). |
| **Token expired** | The app auto-refreshes tokens. If logged out, log in again. |

---

## Keyboard Shortcuts (Desktop App)

| Shortcut | Action |
|----------|--------|
| `Ctrl/Cmd + N` | New job submission |
| `Ctrl/Cmd + R` | Refresh current page |
| `Ctrl/Cmd + 1-4` | Navigate sidebar tabs |

---

*MIT License | Copyright (c) 2026 ByBren, LLC*
