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

"""Certificate management API endpoints for mTLS.

Provides endpoints for issuing and renewing X.509 node certificates,
and for downloading the CA certificate.

Endpoints:
    - ``POST /certs/issue``  -- Issue a signed node certificate.
    - ``GET  /certs/ca``     -- Download the CA certificate (public).
    - ``POST /certs/renew``  -- Renew an expiring node certificate.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from core.relay.tls import CertificateAuthority

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/certs", tags=["certs"])


# --- Request / Response Schemas ---


class CertIssueRequest(BaseModel):
    """Request body for certificate issuance."""

    node_id: str
    csr_pem: str | None = None


class CertIssueResponse(BaseModel):
    """Response body for certificate issuance."""

    node_id: str
    certificate: str
    ca_certificate: str


class CertRenewRequest(BaseModel):
    """Request body for certificate renewal."""

    node_id: str
    current_cert_pem: str
    csr_pem: str | None = None


class CertRenewResponse(BaseModel):
    """Response body for certificate renewal."""

    node_id: str
    certificate: str
    renewed: bool = True


class CACertResponse(BaseModel):
    """Response body for CA certificate download."""

    ca_certificate: str


# --- Helpers ---


def _get_ca_material() -> tuple[bytes, bytes]:
    """Load CA key material from environment or raise 503.

    Returns:
        Tuple of (ca_cert_pem, ca_key_pem).

    Raises:
        HTTPException: 503 if CA is not configured.
    """
    ca_material = CertificateAuthority.load_ca_from_env()
    if ca_material is None:
        logger.error("ca_not_configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Certificate Authority is not configured",
        )
    return ca_material


# --- Endpoints ---


@router.post(
    "/issue",
    response_model=CertIssueResponse,
    status_code=status.HTTP_201_CREATED,
)
async def issue_certificate(
    payload: CertIssueRequest,
) -> CertIssueResponse:
    """Issue a signed node certificate.

    If a CSR is not provided, generates a certificate and key pair
    directly using the CA. The CA certificate is also returned so the
    node can verify the gateway's identity.

    Authentication is expected to be handled upstream (e.g., via node JWT).
    """
    ca_cert_pem, ca_key_pem = _get_ca_material()

    try:
        node_cert_pem, _node_key_pem = CertificateAuthority.issue_node_cert(
            ca_cert_pem=ca_cert_pem,
            ca_key_pem=ca_key_pem,
            node_id=payload.node_id,
        )
    except Exception as exc:
        logger.exception("cert_issuance_failed", node_id=payload.node_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Certificate issuance failed",
        ) from exc

    logger.info("cert_issued_via_api", node_id=payload.node_id)

    return CertIssueResponse(
        node_id=payload.node_id,
        certificate=node_cert_pem.decode(),
        ca_certificate=ca_cert_pem.decode(),
    )


@router.get(
    "/ca",
    response_model=CACertResponse,
)
async def get_ca_certificate() -> CACertResponse:
    """Download the CA certificate.

    This endpoint is public -- it returns only the CA certificate
    (not the CA private key). Nodes need the CA cert to verify the
    gateway's server certificate during mTLS handshake.
    """
    ca_cert_pem, _ca_key_pem = _get_ca_material()

    return CACertResponse(
        ca_certificate=ca_cert_pem.decode(),
    )


@router.post(
    "/renew",
    response_model=CertRenewResponse,
)
async def renew_certificate(
    payload: CertRenewRequest,
) -> CertRenewResponse:
    """Renew an expiring node certificate.

    Validates that the current certificate was issued by this CA,
    then issues a fresh certificate for the same node_id.
    """
    ca_cert_pem, ca_key_pem = _get_ca_material()

    # Verify the current certificate was issued by our CA
    try:
        current_cert_bytes = payload.current_cert_pem.encode()
        if not CertificateAuthority.verify_cert_chain(current_cert_bytes, ca_cert_pem):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Current certificate was not issued by this CA",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("cert_verification_failed", node_id=payload.node_id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid current certificate",
        ) from exc

    # Issue a new certificate
    try:
        new_cert_pem, _new_key_pem = CertificateAuthority.issue_node_cert(
            ca_cert_pem=ca_cert_pem,
            ca_key_pem=ca_key_pem,
            node_id=payload.node_id,
        )
    except Exception as exc:
        logger.exception("cert_renewal_failed", node_id=payload.node_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Certificate renewal failed",
        ) from exc

    logger.info("cert_renewed_via_api", node_id=payload.node_id)

    return CertRenewResponse(
        node_id=payload.node_id,
        certificate=new_cert_pem.decode(),
    )
