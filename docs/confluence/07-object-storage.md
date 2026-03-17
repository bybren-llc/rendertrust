# Object Storage

**Parent**: [RenderTrust System Documentation](00-system-documentation-home.md)

---

## Overview

RenderTrust uses S3-compatible object storage for job payloads and results. The storage layer abstracts across providers (MinIO for development, Cloudflare R2 for production, AWS S3 as fallback) with security features including user-scoped keys, presigned URLs, and AES-256-GCM encryption at rest.

---

## Storage Configuration

| Setting | Development | Production |
|---------|-------------|------------|
| `S3_ENDPOINT` | `http://localhost:9000` | Cloudflare R2 endpoint |
| `S3_BUCKET` | `rendertrust-dev` | `rendertrust-storage` |
| `S3_ACCESS_KEY` | `minioadmin` | Production key (secret) |
| `S3_SECRET_KEY` | `minioadmin` | Production key (secret) |
| `S3_REGION` | `us-east-1` | `auto` (R2) |
| `S3_USE_SSL` | `false` | `true` |

---

## Storage Service API

### Key Format

All storage keys are user-scoped to prevent cross-user access:

```
{user_id}/{job_id}/{filename}
```

Example: `550e8400-e29b-41d4-a716-446655440000/abc-123/result.png`

### Key Validation

Before any operation, keys are validated:

| Rule | Example Violation |
|------|-------------------|
| No empty keys | `""` |
| No leading `/` | `/path/to/file` |
| No `..` (path traversal) | `../other-user/secret` |
| No null bytes | `file\x00name` |

Violations raise `StorageKeyError`.

### Methods

#### `build_key(user_id, job_id, filename="result") -> str`

Constructs a user-scoped storage key:

```python
key = StorageService.build_key("user-uuid", "job-uuid", "output.png")
# Returns: "user-uuid/job-uuid/output.png"
```

#### `upload_file(key, data, content_type="application/octet-stream") -> str`

Uploads bytes or a file-like object to storage.

```python
service.upload_file("user-uuid/job-uuid/result.png", image_bytes, "image/png")
```

#### `download_file(key) -> bytes`

Downloads file contents as bytes.

```python
data = service.download_file("user-uuid/job-uuid/result.png")
```

#### `generate_presigned_url(key, expires_in=3600) -> str`

Creates a time-limited download URL. No authentication needed to use the URL.

```python
url = service.generate_presigned_url("user-uuid/job-uuid/result.png", expires_in=3600)
# Returns: "https://storage.example.com/bucket/key?X-Amz-Signature=..."
```

| Parameter | Range | Default |
|-----------|-------|---------|
| `expires_in` | 1 - 86400 seconds | 3600 (1 hour) |

#### `delete_file(key) -> None`

Deletes a file from storage.

#### `file_exists(key) -> bool`

Checks if a file exists (HEAD request).

---

## Job Result Flow

### Upload (Edge Node → Storage)

```
1. Worker plugin completes execution
2. WorkerExecutor uploads result:
   key = StorageService.build_key(user_id, job_id, "result")
   service.upload_file(key, result_bytes, content_type)
3. Sets result_ref on JobDispatch:
   job.result_ref = f"s3://{bucket}/{key}"
4. Reports COMPLETED status via relay
```

### Download (Creator → Storage)

```
1. Creator requests result:
   GET /api/v1/jobs/{job_id}/result

2. Gateway checks:
   - Job exists? (404 if not)
   - Job COMPLETED? (404 if not)
   - Job has result_ref? (404 if not)

3. Gateway generates presigned URL:
   url = service.generate_presigned_url(key, expires_in=3600)

4. Returns to creator:
   { job_id, download_url, expires_in: 3600 }

5. Creator downloads directly from storage (no gateway proxy)
```

---

## Encryption at Rest

### AES-256-GCM

All stored payloads are encrypted before upload using AES-256-GCM:

```
ENCRYPTION_MASTER_KEY = 32-byte hex key (64 hex chars)
```

**Encryption Process:**
1. Generate random 12-byte nonce (IV)
2. Encrypt plaintext with AES-256-GCM using master key + nonce
3. Store: `nonce || ciphertext || tag`

**Decryption Process:**
1. Extract nonce (first 12 bytes)
2. Extract tag (last 16 bytes)
3. Decrypt ciphertext with AES-256-GCM using master key + nonce + tag

Configuration in `core/storage/encryption.py`.

---

## Development Setup (MinIO)

MinIO runs as part of the development Docker Compose stack:

```yaml
# docker-compose.yml
services:
  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    ports:
      - "9000:9000"   # S3 API
      - "9001:9001"   # Console UI
```

**Console**: http://localhost:9001 (minioadmin/minioadmin)

---

*Apache 2.0 License | Copyright (c) 2026 ByBren, LLC*
