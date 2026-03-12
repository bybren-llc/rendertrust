# Copyright 2026 ByBren, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# ---------------------------------------------------------------------------
# Stage 1 — builder: install Python dependencies from pyproject.toml[edge]
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install system build dependencies required by some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy just the project metadata first so Docker can cache the install layer
COPY pyproject.toml ./

# Copy edgekit source (needed for the edgekit package to be findable)
COPY edgekit/ ./edgekit/

# Install the project with the [edge] extra into a prefix we can copy later.
# Using --prefix keeps installed packages isolated from system packages.
RUN pip install --no-cache-dir --prefix=/install ".[edge]"

# ---------------------------------------------------------------------------
# Stage 2 — runtime: lean image with only what we need
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="ByBren, LLC <contributors@rendertrust.com>"
LABEL description="RenderTrust edge node — relay client + worker executor"

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy edgekit application code
COPY edgekit/ /app/edgekit/

# Copy pyproject.toml for package metadata
COPY pyproject.toml /app/

WORKDIR /app

# Create non-root user for security
RUN groupadd -r edgenode && \
    useradd -r -g edgenode -d /app -s /sbin/nologin edgenode && \
    mkdir -p /data /config && \
    chown -R edgenode:edgenode /app /data /config

# Required environment variables (must be provided at runtime)
ENV GATEWAY_URL="" \
    NODE_JWT="" \
    LOG_LEVEL="INFO" \
    HEALTH_PORT="8081" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

# Expose health check port
EXPOSE 8081

# Switch to non-root user
USER edgenode

# Health check — query the health endpoint every 30 seconds
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')" || exit 1

# Entrypoint: run the edge node entrypoint module
ENTRYPOINT ["python", "-m", "edgekit.entrypoint"]
