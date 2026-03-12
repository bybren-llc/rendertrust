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

"""Tests for mTLS certificate management.

Covers:
    - CA generation (valid X.509, self-signed)
    - Node certificate issuance (signed by CA, correct CN)
    - SSL context creation (server and client)
    - Certificate expiry detection
    - Invalid certificate rejection (wrong CA, expired)
    - Certificate renewal flow
    - Client-side utilities (CSR generation, cert file storage, expiry check)
    - API endpoints (issue, ca, renew)

No external services required -- ephemeral CA and certs are generated in fixtures.
"""

from __future__ import annotations

import datetime
import os
import ssl
import uuid
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

from core.relay.tls import CertificateAuthority
from edgekit.relay.tls import (
    check_cert_expiry,
    generate_csr,
    get_cert_dir,
    load_client_ssl_context,
    save_cert_files,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_blacklist():
    """Mock the token blacklist so verify_token doesn't hit Redis."""
    with patch("core.auth.jwt.token_blacklist") as mock_bl:
        mock_bl.is_revoked = AsyncMock(return_value=False)
        yield mock_bl


@pytest.fixture
def ca_keypair() -> tuple[bytes, bytes]:
    """Generate an ephemeral CA cert and key for testing."""
    return CertificateAuthority.generate_ca()


@pytest.fixture
def node_id() -> str:
    """Return a test node ID."""
    return str(uuid.uuid4())


@pytest.fixture
def node_cert(ca_keypair: tuple[bytes, bytes], node_id: str) -> tuple[bytes, bytes]:
    """Issue an ephemeral node certificate for testing."""
    ca_cert_pem, ca_key_pem = ca_keypair
    return CertificateAuthority.issue_node_cert(
        ca_cert_pem, ca_key_pem, node_id
    )


@pytest.fixture
def second_ca_keypair() -> tuple[bytes, bytes]:
    """Generate a second, independent CA (for wrong-CA tests)."""
    return CertificateAuthority.generate_ca(common_name="Wrong CA")


@pytest.fixture
def cert_tempdir(tmp_path: Path) -> Path:
    """Provide a temporary directory for cert file tests."""
    return tmp_path


# ---------------------------------------------------------------------------
# CA Generation Tests
# ---------------------------------------------------------------------------


class TestCAGeneration:
    """Tests for CertificateAuthority.generate_ca()."""

    def test_generate_ca_returns_pem_bytes(self, ca_keypair: tuple[bytes, bytes]):
        """CA cert and key should be PEM-encoded bytes."""
        ca_cert_pem, ca_key_pem = ca_keypair
        assert isinstance(ca_cert_pem, bytes)
        assert isinstance(ca_key_pem, bytes)
        assert b"-----BEGIN CERTIFICATE-----" in ca_cert_pem
        assert b"-----BEGIN PRIVATE KEY-----" in ca_key_pem

    def test_generate_ca_is_self_signed(self, ca_keypair: tuple[bytes, bytes]):
        """CA certificate should be self-signed (subject == issuer)."""
        ca_cert_pem, _ = ca_keypair
        cert = x509.load_pem_x509_certificate(ca_cert_pem)
        assert cert.subject == cert.issuer

    def test_generate_ca_has_correct_cn(self, ca_keypair: tuple[bytes, bytes]):
        """CA certificate should have the expected Common Name."""
        ca_cert_pem, _ = ca_keypair
        cert = x509.load_pem_x509_certificate(ca_cert_pem)
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        assert len(cn_attrs) == 1
        assert cn_attrs[0].value == "RenderTrust Internal CA"

    def test_generate_ca_custom_cn(self):
        """CA generation with custom CN should use that CN."""
        cert_pem, _ = CertificateAuthority.generate_ca(common_name="Test CA")
        cert = x509.load_pem_x509_certificate(cert_pem)
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == "Test CA"

    def test_generate_ca_is_valid_x509(self, ca_keypair: tuple[bytes, bytes]):
        """CA certificate should be a valid X.509 certificate."""
        ca_cert_pem, _ = ca_keypair
        cert = x509.load_pem_x509_certificate(ca_cert_pem)
        # Should have basic constraints with CA=True
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is True

    def test_generate_ca_key_is_rsa_4096(self, ca_keypair: tuple[bytes, bytes]):
        """CA private key should be RSA with 4096-bit key size."""
        _, ca_key_pem = ca_keypair
        key = serialization.load_pem_private_key(ca_key_pem, password=None)
        assert key.key_size == 4096

    def test_generate_ca_custom_validity(self):
        """CA cert with custom validity period should have correct not_valid_after."""
        cert_pem, _ = CertificateAuthority.generate_ca(days=365)
        cert = x509.load_pem_x509_certificate(cert_pem)
        now = datetime.datetime.now(tz=datetime.UTC)
        expected = now + datetime.timedelta(days=365)
        # Allow 60 seconds tolerance for test execution time
        delta = abs((cert.not_valid_after_utc - expected).total_seconds())
        assert delta < 60


# ---------------------------------------------------------------------------
# Node Certificate Issuance Tests
# ---------------------------------------------------------------------------


class TestNodeCertIssuance:
    """Tests for CertificateAuthority.issue_node_cert()."""

    def test_issue_node_cert_returns_pem(self, node_cert: tuple[bytes, bytes]):
        """Node cert and key should be PEM-encoded bytes."""
        cert_pem, key_pem = node_cert
        assert b"-----BEGIN CERTIFICATE-----" in cert_pem
        assert b"-----BEGIN PRIVATE KEY-----" in key_pem

    def test_issue_node_cert_has_correct_cn(
        self, node_cert: tuple[bytes, bytes], node_id: str
    ):
        """Node certificate CN should match the expected format."""
        cert_pem, _ = node_cert
        cert = x509.load_pem_x509_certificate(cert_pem)
        cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == f"node-{node_id}.rendertrust.local"

    def test_issue_node_cert_signed_by_ca(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
    ):
        """Node certificate should be signed by the CA."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, _ = node_cert
        assert CertificateAuthority.verify_cert_chain(cert_pem, ca_cert_pem) is True

    def test_issue_node_cert_not_ca(self, node_cert: tuple[bytes, bytes]):
        """Node certificate should NOT be a CA certificate."""
        cert_pem, _ = node_cert
        cert = x509.load_pem_x509_certificate(cert_pem)
        bc = cert.extensions.get_extension_for_class(x509.BasicConstraints)
        assert bc.value.ca is False

    def test_issue_node_cert_has_san(
        self, node_cert: tuple[bytes, bytes], node_id: str
    ):
        """Node certificate should have a SubjectAlternativeName."""
        cert_pem, _ = node_cert
        cert = x509.load_pem_x509_certificate(cert_pem)
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        )
        dns_names = san.value.get_values_for_type(x509.DNSName)
        assert f"node-{node_id}.rendertrust.local" in dns_names

    def test_issue_node_cert_has_client_auth_eku(
        self, node_cert: tuple[bytes, bytes]
    ):
        """Node certificate should have CLIENT_AUTH extended key usage."""
        cert_pem, _ = node_cert
        cert = x509.load_pem_x509_certificate(cert_pem)
        eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH in eku.value

    def test_issue_node_cert_key_is_rsa_2048(
        self, node_cert: tuple[bytes, bytes]
    ):
        """Node private key should be RSA with 2048-bit key size."""
        _, key_pem = node_cert
        key = serialization.load_pem_private_key(key_pem, password=None)
        assert key.key_size == 2048

    def test_issue_node_cert_different_issuer_than_subject(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
    ):
        """Node cert issuer should be the CA subject, not self."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, _ = node_cert

        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        node_cert_obj = x509.load_pem_x509_certificate(cert_pem)

        assert node_cert_obj.issuer == ca_cert.subject
        assert node_cert_obj.subject != node_cert_obj.issuer


# ---------------------------------------------------------------------------
# SSL Context Tests
# ---------------------------------------------------------------------------


class TestSSLContext:
    """Tests for SSL context creation (server and client)."""

    def test_create_server_ssl_context(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
        cert_tempdir: Path,
    ):
        """Server SSL context should be created with CERT_REQUIRED."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, key_pem = node_cert

        ca_path = cert_tempdir / "ca.pem"
        cert_path = cert_tempdir / "server.pem"
        key_path = cert_tempdir / "server-key.pem"

        ca_path.write_bytes(ca_cert_pem)
        cert_path.write_bytes(cert_pem)
        key_path.write_bytes(key_pem)

        ctx = CertificateAuthority.create_ssl_context(
            ca_cert_path=str(ca_path),
            server_cert_path=str(cert_path),
            server_key_path=str(key_path),
        )

        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_create_server_ssl_context_missing_file(self, cert_tempdir: Path):
        """SSL context creation should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="CA certificate not found"):
            CertificateAuthority.create_ssl_context(
                ca_cert_path=str(cert_tempdir / "nonexistent-ca.pem"),
                server_cert_path=str(cert_tempdir / "server.pem"),
                server_key_path=str(cert_tempdir / "server-key.pem"),
            )

    def test_create_client_ssl_context(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
        cert_tempdir: Path,
    ):
        """Client SSL context should be created with CERT_REQUIRED."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, key_pem = node_cert

        ca_path = cert_tempdir / "ca.pem"
        cert_path = cert_tempdir / "client.pem"
        key_path = cert_tempdir / "client-key.pem"

        ca_path.write_bytes(ca_cert_pem)
        cert_path.write_bytes(cert_pem)
        key_path.write_bytes(key_pem)

        ctx = load_client_ssl_context(
            cert_path=str(cert_path),
            key_path=str(key_path),
            ca_cert_path=str(ca_path),
        )

        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED

    def test_client_ssl_context_missing_file(self, cert_tempdir: Path):
        """Client SSL context should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError, match="client certificate not found"):
            load_client_ssl_context(
                cert_path=str(cert_tempdir / "nonexistent-client.pem"),
                key_path=str(cert_tempdir / "client-key.pem"),
                ca_cert_path=str(cert_tempdir / "ca.pem"),
            )


# ---------------------------------------------------------------------------
# Certificate Expiry Detection Tests
# ---------------------------------------------------------------------------


class TestCertExpiry:
    """Tests for certificate expiry detection."""

    def test_cert_not_expiring_soon(self, node_cert: tuple[bytes, bytes]):
        """A freshly issued 90-day cert should not be expiring soon."""
        cert_pem, _ = node_cert
        assert CertificateAuthority.is_cert_expiring_soon(cert_pem) is False

    def test_cert_expiring_soon_with_threshold(
        self,
        ca_keypair: tuple[bytes, bytes],
    ):
        """A cert valid for 10 days should be expiring soon with 30-day threshold."""
        ca_cert_pem, ca_key_pem = ca_keypair
        # Issue a cert valid for only 10 days
        cert_pem, _ = CertificateAuthority.issue_node_cert(
            ca_cert_pem, ca_key_pem, "short-lived", days=10
        )
        assert CertificateAuthority.is_cert_expiring_soon(cert_pem, threshold_days=30) is True
        assert CertificateAuthority.is_cert_expiring_soon(cert_pem, threshold_days=5) is False

    def test_check_cert_expiry_returns_dict(self, node_cert: tuple[bytes, bytes]):
        """check_cert_expiry should return a well-formed status dict."""
        cert_pem, _ = node_cert
        result = check_cert_expiry(cert_pem)

        assert "not_valid_after" in result
        assert "days_remaining" in result
        assert "is_expired" in result
        assert "is_expiring_soon" in result
        assert result["is_expired"] is False
        assert result["days_remaining"] > 0

    def test_get_cert_expiry_returns_datetime(
        self, node_cert: tuple[bytes, bytes]
    ):
        """get_cert_expiry should return a UTC datetime."""
        cert_pem, _ = node_cert
        expiry = CertificateAuthority.get_cert_expiry(cert_pem)
        assert isinstance(expiry, datetime.datetime)
        assert expiry.tzinfo is not None

    def test_get_cert_cn(
        self, node_cert: tuple[bytes, bytes], node_id: str
    ):
        """get_cert_cn should extract the CN from the certificate."""
        cert_pem, _ = node_cert
        cn = CertificateAuthority.get_cert_cn(cert_pem)
        assert cn == f"node-{node_id}.rendertrust.local"


# ---------------------------------------------------------------------------
# Invalid Certificate Rejection Tests
# ---------------------------------------------------------------------------


class TestCertRejection:
    """Tests for invalid certificate rejection."""

    def test_reject_cert_from_wrong_ca(
        self,
        node_cert: tuple[bytes, bytes],
        second_ca_keypair: tuple[bytes, bytes],
    ):
        """A cert signed by CA-A should NOT verify against CA-B."""
        cert_pem, _ = node_cert
        wrong_ca_cert_pem, _ = second_ca_keypair

        result = CertificateAuthority.verify_cert_chain(cert_pem, wrong_ca_cert_pem)
        assert result is False

    def test_verify_cert_chain_valid(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
    ):
        """A cert signed by CA should verify against that CA."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, _ = node_cert

        result = CertificateAuthority.verify_cert_chain(cert_pem, ca_cert_pem)
        assert result is True

    def test_verify_self_signed_ca(self, ca_keypair: tuple[bytes, bytes]):
        """A self-signed CA cert should verify against itself."""
        ca_cert_pem, _ = ca_keypair
        result = CertificateAuthority.verify_cert_chain(ca_cert_pem, ca_cert_pem)
        assert result is True


# ---------------------------------------------------------------------------
# Client-side Utilities Tests
# ---------------------------------------------------------------------------


class TestClientUtilities:
    """Tests for edgekit.relay.tls client utilities."""

    def test_generate_csr(self, node_id: str):
        """generate_csr should return valid CSR and key PEM."""
        csr_pem, key_pem = generate_csr(node_id)
        assert b"-----BEGIN CERTIFICATE REQUEST-----" in csr_pem
        assert b"-----BEGIN PRIVATE KEY-----" in key_pem

        # Verify CSR CN
        csr = x509.load_pem_x509_csr(csr_pem)
        cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == f"node-{node_id}.rendertrust.local"

    def test_save_cert_files(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
        node_id: str,
        cert_tempdir: Path,
    ):
        """save_cert_files should write cert, key, and CA files."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, key_pem = node_cert

        paths = save_cert_files(
            node_id=node_id,
            cert_pem=cert_pem,
            key_pem=key_pem,
            ca_cert_pem=ca_cert_pem,
            cert_dir=cert_tempdir,
        )

        assert paths["cert_path"].exists()
        assert paths["key_path"].exists()
        assert paths["ca_cert_path"].exists()

        # Verify file contents
        assert paths["cert_path"].read_bytes() == cert_pem
        assert paths["key_path"].read_bytes() == key_pem
        assert paths["ca_cert_path"].read_bytes() == ca_cert_pem

    def test_save_cert_files_key_permissions(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
        node_id: str,
        cert_tempdir: Path,
    ):
        """Private key file should have restrictive permissions (0o600)."""
        ca_cert_pem, _ = ca_keypair
        cert_pem, key_pem = node_cert

        paths = save_cert_files(
            node_id=node_id,
            cert_pem=cert_pem,
            key_pem=key_pem,
            ca_cert_pem=ca_cert_pem,
            cert_dir=cert_tempdir,
        )

        key_mode = paths["key_path"].stat().st_mode & 0o777
        assert key_mode == 0o600

    def test_get_cert_dir_creates_directory(self, tmp_path: Path):
        """get_cert_dir should create the directory if it does not exist."""
        new_dir = tmp_path / "new_certs"
        assert not new_dir.exists()
        result = get_cert_dir(new_dir)
        assert result.exists()
        assert result == new_dir


# ---------------------------------------------------------------------------
# Certificate Renewal Flow Tests
# ---------------------------------------------------------------------------


class TestCertRenewal:
    """Tests for the certificate renewal flow."""

    def test_renew_produces_new_cert(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_cert: tuple[bytes, bytes],
        node_id: str,
    ):
        """Renewing should produce a different certificate with the same CN."""
        ca_cert_pem, ca_key_pem = ca_keypair
        old_cert_pem, _ = node_cert

        # Issue a new cert (simulating renewal)
        new_cert_pem, new_key_pem = CertificateAuthority.issue_node_cert(
            ca_cert_pem, ca_key_pem, node_id
        )

        # Different cert bytes (different serial number, key)
        assert new_cert_pem != old_cert_pem
        assert new_key_pem is not None

        # Same CN
        old_cn = CertificateAuthority.get_cert_cn(old_cert_pem)
        new_cn = CertificateAuthority.get_cert_cn(new_cert_pem)
        assert old_cn == new_cn

    def test_renewed_cert_signed_by_same_ca(
        self,
        ca_keypair: tuple[bytes, bytes],
        node_id: str,
    ):
        """A renewed certificate should still be signed by the same CA."""
        ca_cert_pem, ca_key_pem = ca_keypair
        renewed_cert_pem, _ = CertificateAuthority.issue_node_cert(
            ca_cert_pem, ca_key_pem, node_id
        )
        assert CertificateAuthority.verify_cert_chain(
            renewed_cert_pem, ca_cert_pem
        ) is True


# ---------------------------------------------------------------------------
# CA Environment Loading Tests
# ---------------------------------------------------------------------------


class TestCAEnvLoading:
    """Tests for CA material loading from environment."""

    def test_load_ca_from_env_inline(
        self, ca_keypair: tuple[bytes, bytes]
    ):
        """Should load CA from inline PEM env vars."""
        ca_cert_pem, ca_key_pem = ca_keypair
        with patch.dict(os.environ, {
            "RENDERTRUST_CA_CERT": ca_cert_pem.decode(),
            "RENDERTRUST_CA_KEY": ca_key_pem.decode(),
        }, clear=False):
            result = CertificateAuthority.load_ca_from_env()
            assert result is not None
            assert result[0] == ca_cert_pem
            assert result[1] == ca_key_pem

    def test_load_ca_from_env_files(
        self,
        ca_keypair: tuple[bytes, bytes],
        cert_tempdir: Path,
    ):
        """Should load CA from file path env vars."""
        ca_cert_pem, ca_key_pem = ca_keypair
        cert_path = cert_tempdir / "ca.pem"
        key_path = cert_tempdir / "ca-key.pem"
        cert_path.write_bytes(ca_cert_pem)
        key_path.write_bytes(ca_key_pem)

        env = {
            "RENDERTRUST_CA_CERT_PATH": str(cert_path),
            "RENDERTRUST_CA_KEY_PATH": str(key_path),
        }
        # Clear the inline vars to test file path fallback
        env["RENDERTRUST_CA_CERT"] = ""
        env["RENDERTRUST_CA_KEY"] = ""

        with patch.dict(os.environ, env, clear=False):
            result = CertificateAuthority.load_ca_from_env()
            assert result is not None
            assert result[0] == ca_cert_pem

    def test_load_ca_from_env_none_when_unconfigured(self):
        """Should return None when no CA env vars are set."""
        env_clear = {
            "RENDERTRUST_CA_CERT": "",
            "RENDERTRUST_CA_KEY": "",
            "RENDERTRUST_CA_CERT_PATH": "",
            "RENDERTRUST_CA_KEY_PATH": "",
        }
        with patch.dict(os.environ, env_clear, clear=False):
            result = CertificateAuthority.load_ca_from_env()
            assert result is None


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------


class TestCertsAPI:
    """Tests for the certificate management API endpoints."""

    @pytest.fixture
    def ca_env(self, ca_keypair: tuple[bytes, bytes]):
        """Set up CA env vars for API tests."""
        ca_cert_pem, ca_key_pem = ca_keypair
        with patch.dict(os.environ, {
            "RENDERTRUST_CA_CERT": ca_cert_pem.decode(),
            "RENDERTRUST_CA_KEY": ca_key_pem.decode(),
        }, clear=False):
            yield ca_cert_pem, ca_key_pem

    async def test_issue_certificate_endpoint(
        self, client, ca_env, node_id: str
    ):
        """POST /certs/issue should return a signed certificate."""
        response = await client.post(
            "/api/v1/certs/issue",
            json={"node_id": node_id},
        )
        assert response.status_code == 201
        data = response.json()
        assert data["node_id"] == node_id
        assert "-----BEGIN CERTIFICATE-----" in data["certificate"]
        assert "-----BEGIN CERTIFICATE-----" in data["ca_certificate"]

    async def test_get_ca_certificate_endpoint(self, client, ca_env):
        """GET /certs/ca should return the CA certificate."""
        response = await client.get("/api/v1/certs/ca")
        assert response.status_code == 200
        data = response.json()
        assert "-----BEGIN CERTIFICATE-----" in data["ca_certificate"]

    async def test_renew_certificate_endpoint(
        self, client, ca_env, node_id: str
    ):
        """POST /certs/renew should return a renewed certificate."""
        ca_cert_pem, ca_key_pem = ca_env
        # First issue a cert
        cert_pem, _ = CertificateAuthority.issue_node_cert(
            ca_cert_pem, ca_key_pem, node_id
        )

        response = await client.post(
            "/api/v1/certs/renew",
            json={
                "node_id": node_id,
                "current_cert_pem": cert_pem.decode(),
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["node_id"] == node_id
        assert data["renewed"] is True
        assert "-----BEGIN CERTIFICATE-----" in data["certificate"]

    async def test_renew_rejects_wrong_ca_cert(
        self, client, ca_env, second_ca_keypair, node_id: str
    ):
        """POST /certs/renew should reject a cert from a different CA."""
        wrong_ca_cert_pem, wrong_ca_key_pem = second_ca_keypair
        # Issue a cert from the WRONG CA
        wrong_cert_pem, _ = CertificateAuthority.issue_node_cert(
            wrong_ca_cert_pem, wrong_ca_key_pem, node_id
        )

        response = await client.post(
            "/api/v1/certs/renew",
            json={
                "node_id": node_id,
                "current_cert_pem": wrong_cert_pem.decode(),
            },
        )
        assert response.status_code == 400
        assert "not issued by this CA" in response.json()["detail"]

    async def test_issue_cert_no_ca_configured(self, client, node_id: str):
        """POST /certs/issue should return 503 when CA is not configured."""
        env_clear = {
            "RENDERTRUST_CA_CERT": "",
            "RENDERTRUST_CA_KEY": "",
            "RENDERTRUST_CA_CERT_PATH": "",
            "RENDERTRUST_CA_KEY_PATH": "",
        }
        with patch.dict(os.environ, env_clear, clear=False):
            response = await client.post(
                "/api/v1/certs/issue",
                json={"node_id": node_id},
            )
            assert response.status_code == 503
            assert "not configured" in response.json()["detail"]
