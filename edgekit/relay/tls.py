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

"""Client-side mTLS certificate management for edge nodes.

Handles loading, storing, and renewing X.509 client certificates used
for mutual TLS authentication between edge nodes and the gateway relay.

Certificates are stored under ``~/.edgekit/certs/`` by default.
"""

from __future__ import annotations

import datetime
import ssl
from pathlib import Path
from typing import Any

import httpx
import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = structlog.get_logger(__name__)

# Default cert storage directory
_DEFAULT_CERT_DIR = Path.home() / ".edgekit" / "certs"
_CSR_KEY_SIZE = 2048
_EXPIRY_THRESHOLD_DAYS = 30


def get_cert_dir(cert_dir: str | Path | None = None) -> Path:
    """Return the certificate storage directory, creating it if needed.

    Args:
        cert_dir: Optional override for the certificate directory.

    Returns:
        Path to the certificate directory.
    """
    path = Path(cert_dir) if cert_dir else _DEFAULT_CERT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_csr(
    node_id: str,
    key_size: int = _CSR_KEY_SIZE,
) -> tuple[bytes, bytes]:
    """Generate a Certificate Signing Request (CSR) and private key.

    Args:
        node_id: The node identifier for the CN field.
        key_size: RSA key size (default 2048).

    Returns:
        Tuple of (csr_pem, private_key_pem) as PEM-encoded bytes.
    """
    cn = f"node-{node_id}.rendertrust.local"

    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
    )

    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, cn),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RenderTrust"),
            x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Edge Nodes"),
        ]))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(cn)]),
            critical=False,
        )
        .sign(private_key, hashes.SHA256())
    )

    csr_pem = csr.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    logger.info("csr_generated", node_id=node_id, cn=cn)
    return csr_pem, key_pem


def load_client_ssl_context(
    cert_path: str | Path,
    key_path: str | Path,
    ca_cert_path: str | Path,
) -> ssl.SSLContext:
    """Create an SSL context for the mTLS client.

    Args:
        cert_path: Path to the client certificate PEM file.
        key_path: Path to the client private key PEM file.
        ca_cert_path: Path to the CA certificate PEM file.

    Returns:
        Configured ``ssl.SSLContext`` for mutual TLS client connections.

    Raises:
        FileNotFoundError: If any certificate file does not exist.
    """
    cert_path = Path(cert_path)
    key_path = Path(key_path)
    ca_cert_path = Path(ca_cert_path)

    for path, label in [
        (cert_path, "client certificate"),
        (key_path, "client key"),
        (ca_cert_path, "CA certificate"),
    ]:
        if not path.exists():
            msg = f"{label} not found: {path}"
            raise FileNotFoundError(msg)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    ctx.load_verify_locations(cafile=str(ca_cert_path))

    # Require server certificate verification
    ctx.check_hostname = False  # We use internal CAs, not public DNS
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    logger.info(
        "client_ssl_context_created",
        cert=str(cert_path),
        ca_cert=str(ca_cert_path),
    )

    return ctx


async def request_certificate(
    gateway_url: str,
    node_id: str,
    csr_pem: bytes,
    auth_token: str | None = None,
) -> bytes:
    """Request a signed certificate from the gateway.

    Sends the CSR to the gateway's certificate issuance endpoint
    and returns the signed certificate PEM.

    Args:
        gateway_url: Base URL of the gateway (e.g. ``https://gateway.rendertrust.local``).
        node_id: The node identifier.
        csr_pem: PEM-encoded Certificate Signing Request.
        auth_token: Optional Bearer token for authentication.

    Returns:
        PEM-encoded signed certificate bytes.

    Raises:
        httpx.HTTPStatusError: If the gateway rejects the request.
    """
    url = f"{gateway_url.rstrip('/')}/api/v1/certs/issue"

    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    logger.info(
        "requesting_certificate",
        node_id=node_id,
        gateway_url=gateway_url,
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={
                "node_id": node_id,
                "csr_pem": csr_pem.decode(),
            },
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()

    data = response.json()
    cert_pem = data["certificate"].encode()

    logger.info("certificate_received", node_id=node_id)
    return cert_pem


async def request_renewal(
    gateway_url: str,
    node_id: str,
    current_cert_pem: bytes,
    csr_pem: bytes,
    auth_token: str | None = None,
) -> bytes:
    """Request renewal of an expiring certificate.

    Args:
        gateway_url: Base URL of the gateway.
        node_id: The node identifier.
        current_cert_pem: The current (expiring) certificate PEM.
        csr_pem: A new CSR for the renewed certificate.
        auth_token: Optional Bearer token for authentication.

    Returns:
        PEM-encoded renewed certificate bytes.

    Raises:
        httpx.HTTPStatusError: If the gateway rejects the request.
    """
    url = f"{gateway_url.rstrip('/')}/api/v1/certs/renew"

    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    logger.info("requesting_certificate_renewal", node_id=node_id)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json={
                "node_id": node_id,
                "current_cert_pem": current_cert_pem.decode(),
                "csr_pem": csr_pem.decode(),
            },
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()

    data = response.json()
    cert_pem = data["certificate"].encode()

    logger.info("certificate_renewed", node_id=node_id)
    return cert_pem


def check_cert_expiry(
    cert_pem: bytes,
    threshold_days: int = _EXPIRY_THRESHOLD_DAYS,
) -> dict[str, Any]:
    """Check the expiry status of a certificate.

    Args:
        cert_pem: PEM-encoded certificate bytes.
        threshold_days: Days before expiry to flag as expiring (default 30).

    Returns:
        Dictionary with keys:
            - ``not_valid_after``: Expiry datetime (UTC).
            - ``days_remaining``: Days until expiry.
            - ``is_expired``: True if already expired.
            - ``is_expiring_soon``: True if within threshold.
    """
    cert = x509.load_pem_x509_certificate(cert_pem)
    now = datetime.datetime.now(tz=datetime.UTC)
    expiry = cert.not_valid_after_utc
    remaining = expiry - now
    days_remaining = remaining.total_seconds() / 86400

    return {
        "not_valid_after": expiry,
        "days_remaining": days_remaining,
        "is_expired": days_remaining < 0,
        "is_expiring_soon": 0 <= days_remaining < threshold_days,
    }


def save_cert_files(
    node_id: str,
    cert_pem: bytes,
    key_pem: bytes,
    ca_cert_pem: bytes,
    cert_dir: str | Path | None = None,
) -> dict[str, Path]:
    """Save certificate files to the local filesystem.

    Args:
        node_id: The node identifier (used in filenames).
        cert_pem: PEM-encoded node certificate.
        key_pem: PEM-encoded node private key.
        ca_cert_pem: PEM-encoded CA certificate.
        cert_dir: Optional override for the certificate directory.

    Returns:
        Dictionary with paths: ``cert_path``, ``key_path``, ``ca_cert_path``.
    """
    directory = get_cert_dir(cert_dir)

    cert_path = directory / f"node-{node_id}.pem"
    key_path = directory / f"node-{node_id}-key.pem"
    ca_cert_path = directory / "ca.pem"

    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    # Set restrictive permissions on private key
    key_path.chmod(0o600)
    ca_cert_path.write_bytes(ca_cert_pem)

    logger.info(
        "cert_files_saved",
        node_id=node_id,
        cert_dir=str(directory),
    )

    return {
        "cert_path": cert_path,
        "key_path": key_path,
        "ca_cert_path": ca_cert_path,
    }
