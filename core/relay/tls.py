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

"""Server-side mTLS module for edge node transport security.

Provides a Certificate Authority (CA) implementation for issuing and
verifying X.509 certificates used in mutual TLS between the gateway
and edge nodes.

Key classes:
    - ``CertificateAuthority`` -- Generate CA, issue node certs, create SSL contexts.

CA key material is loaded from environment variables
(``RENDERTRUST_CA_CERT``, ``RENDERTRUST_CA_KEY``) or from file paths.
"""

from __future__ import annotations

import datetime
import os
import ssl
from pathlib import Path

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = structlog.get_logger(__name__)

# Certificate defaults
_CA_KEY_SIZE = 4096
_NODE_KEY_SIZE = 2048
_CA_DEFAULT_DAYS = 3650
_NODE_DEFAULT_DAYS = 90
_CA_COMMON_NAME = "RenderTrust Internal CA"
_NODE_CN_FORMAT = "node-{node_id}.rendertrust.local"


class CertificateAuthority:
    """X.509 Certificate Authority for edge node mTLS.

    Generates a self-signed CA certificate and issues node certificates
    signed by the CA. All certificates use RSA keys.

    Example::

        ca = CertificateAuthority()
        ca_cert_pem, ca_key_pem = ca.generate_ca()
        node_cert_pem, node_key_pem = ca.issue_node_cert(
            ca_cert_pem, ca_key_pem, "abc123"
        )
        ssl_ctx = ca.create_ssl_context(
            ca_cert_path="/path/to/ca.pem",
            server_cert_path="/path/to/server.pem",
            server_key_path="/path/to/server-key.pem",
        )
    """

    @staticmethod
    def generate_ca(
        common_name: str = _CA_COMMON_NAME,
        days: int = _CA_DEFAULT_DAYS,
    ) -> tuple[bytes, bytes]:
        """Generate a self-signed CA certificate and private key.

        Args:
            common_name: The Common Name (CN) for the CA certificate.
            days: Validity period in days (default 3650 = ~10 years).

        Returns:
            Tuple of (ca_cert_pem, ca_key_pem) as PEM-encoded bytes.
        """
        logger.info("generating_ca_certificate", common_name=common_name, days=days)

        # Generate RSA 4096 key for CA
        ca_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=_CA_KEY_SIZE,
        )

        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RenderTrust"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Infrastructure"),
            ]
        )

        now = datetime.datetime.now(tz=datetime.UTC)
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_cert_sign=True,
                    crl_sign=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        ca_cert_pem = ca_cert.public_bytes(serialization.Encoding.PEM)
        ca_key_pem = ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        logger.info(
            "ca_certificate_generated",
            serial=str(ca_cert.serial_number),
            not_after=str(ca_cert.not_valid_after_utc),
        )

        return ca_cert_pem, ca_key_pem

    @staticmethod
    def issue_node_cert(
        ca_cert_pem: bytes,
        ca_key_pem: bytes,
        node_id: str,
        days: int = _NODE_DEFAULT_DAYS,
    ) -> tuple[bytes, bytes]:
        """Issue a node certificate signed by the CA.

        Args:
            ca_cert_pem: PEM-encoded CA certificate bytes.
            ca_key_pem: PEM-encoded CA private key bytes.
            node_id: The node identifier (used in the CN and SAN).
            days: Validity period in days (default 90).

        Returns:
            Tuple of (node_cert_pem, node_key_pem) as PEM-encoded bytes.

        Raises:
            ValueError: If ca_cert_pem or ca_key_pem is invalid.
        """
        logger.info("issuing_node_certificate", node_id=node_id, days=days)

        # Load CA certificate and key
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
        ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)

        # Generate RSA 2048 key for node
        node_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=_NODE_KEY_SIZE,
        )

        cn = _NODE_CN_FORMAT.format(node_id=node_id)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, cn),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RenderTrust"),
                x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Edge Nodes"),
            ]
        )

        now = datetime.datetime.now(tz=datetime.UTC)
        node_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(node_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    key_encipherment=True,
                    content_commitment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage(
                    [
                        x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                    ]
                ),
                critical=False,
            )
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName(cn),
                    ]
                ),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        node_cert_pem = node_cert.public_bytes(serialization.Encoding.PEM)
        node_key_pem = node_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )

        logger.info(
            "node_certificate_issued",
            node_id=node_id,
            cn=cn,
            serial=str(node_cert.serial_number),
            not_after=str(node_cert.not_valid_after_utc),
        )

        return node_cert_pem, node_key_pem

    @staticmethod
    def create_ssl_context(
        ca_cert_path: str | Path,
        server_cert_path: str | Path,
        server_key_path: str | Path,
    ) -> ssl.SSLContext:
        """Create an SSL context for the mTLS server.

        Configures the context to require client certificates and verify
        them against the CA certificate.

        Args:
            ca_cert_path: Path to the CA certificate PEM file.
            server_cert_path: Path to the server certificate PEM file.
            server_key_path: Path to the server private key PEM file.

        Returns:
            Configured ``ssl.SSLContext`` requiring mutual TLS.

        Raises:
            FileNotFoundError: If any certificate file does not exist.
        """
        ca_cert_path = Path(ca_cert_path)
        server_cert_path = Path(server_cert_path)
        server_key_path = Path(server_key_path)

        for path, label in [
            (ca_cert_path, "CA certificate"),
            (server_cert_path, "server certificate"),
            (server_key_path, "server key"),
        ]:
            if not path.exists():
                msg = f"{label} not found: {path}"
                raise FileNotFoundError(msg)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=str(ca_cert_path))
        ctx.load_cert_chain(
            certfile=str(server_cert_path),
            keyfile=str(server_key_path),
        )

        # Disable insecure protocols
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        logger.info(
            "ssl_context_created",
            ca_cert=str(ca_cert_path),
            server_cert=str(server_cert_path),
        )

        return ctx

    @staticmethod
    def load_ca_from_env() -> tuple[bytes, bytes] | None:
        """Load CA certificate and key from environment variables.

        Checks ``RENDERTRUST_CA_CERT`` and ``RENDERTRUST_CA_KEY`` for
        PEM-encoded content. Falls back to ``RENDERTRUST_CA_CERT_PATH``
        and ``RENDERTRUST_CA_KEY_PATH`` for file path references.

        Returns:
            Tuple of (ca_cert_pem, ca_key_pem) or None if not configured.
        """
        # Try inline PEM from env vars
        ca_cert_env = os.environ.get("RENDERTRUST_CA_CERT")
        ca_key_env = os.environ.get("RENDERTRUST_CA_KEY")

        if ca_cert_env and ca_key_env:
            logger.info("loading_ca_from_env_vars")
            return ca_cert_env.encode(), ca_key_env.encode()

        # Try file paths
        ca_cert_path = os.environ.get("RENDERTRUST_CA_CERT_PATH")
        ca_key_path = os.environ.get("RENDERTRUST_CA_KEY_PATH")

        if ca_cert_path and ca_key_path:
            cert_path = Path(ca_cert_path)
            key_path = Path(ca_key_path)
            if cert_path.exists() and key_path.exists():
                logger.info(
                    "loading_ca_from_files",
                    cert_path=ca_cert_path,
                    key_path=ca_key_path,
                )
                return cert_path.read_bytes(), key_path.read_bytes()
            logger.warning(
                "ca_file_not_found",
                cert_exists=cert_path.exists(),
                key_exists=key_path.exists(),
            )

        logger.debug("no_ca_configured_in_env")
        return None

    @staticmethod
    def get_cert_expiry(cert_pem: bytes) -> datetime.datetime:
        """Extract the expiry date from a PEM-encoded certificate.

        Args:
            cert_pem: PEM-encoded certificate bytes.

        Returns:
            The ``not_valid_after`` datetime (UTC-aware).
        """
        cert = x509.load_pem_x509_certificate(cert_pem)
        return cert.not_valid_after_utc

    @staticmethod
    def get_cert_cn(cert_pem: bytes) -> str | None:
        """Extract the Common Name from a PEM-encoded certificate.

        Args:
            cert_pem: PEM-encoded certificate bytes.

        Returns:
            The CN string, or None if not present.
        """
        cert = x509.load_pem_x509_certificate(cert_pem)
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if cn_attrs:
            return str(cn_attrs[0].value)
        return None

    @staticmethod
    def is_cert_expiring_soon(
        cert_pem: bytes,
        threshold_days: int = 30,
    ) -> bool:
        """Check if a certificate is expiring within the given threshold.

        Args:
            cert_pem: PEM-encoded certificate bytes.
            threshold_days: Number of days before expiry to trigger (default 30).

        Returns:
            True if the certificate expires within ``threshold_days``.
        """
        expiry = CertificateAuthority.get_cert_expiry(cert_pem)
        now = datetime.datetime.now(tz=datetime.UTC)
        remaining = expiry - now
        return remaining.total_seconds() < threshold_days * 86400

    @staticmethod
    def verify_cert_chain(
        cert_pem: bytes,
        ca_cert_pem: bytes,
    ) -> bool:
        """Verify that a certificate was signed by the given CA.

        Args:
            cert_pem: PEM-encoded certificate to verify.
            ca_cert_pem: PEM-encoded CA certificate.

        Returns:
            True if the certificate was signed by the CA, False otherwise.
        """
        from cryptography.hazmat.primitives.asymmetric import padding

        try:
            cert = x509.load_pem_x509_certificate(cert_pem)
            ca_cert = x509.load_pem_x509_certificate(ca_cert_pem)
            ca_public_key = ca_cert.public_key()

            # RSA keys require padding and prehashed arguments
            hash_algo = cert.signature_hash_algorithm
            ca_public_key.verify(
                cert.signature,
                cert.tbs_certificate_bytes,
                padding.PKCS1v15(),
                hash_algo,
            )
            return True
        except Exception:
            logger.debug("cert_chain_verification_failed")
            return False
