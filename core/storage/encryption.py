# Copyright 2025 ByBren, LLC
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

"""Data-at-rest encryption service using AES-256-GCM.

Provides transparent encryption for stored files with per-user key derivation
via HKDF-SHA256. The wire format prepends the 12-byte IV and 16-byte GCM
authentication tag to the ciphertext:

    [12-byte IV][16-byte auth tag][ciphertext]

Usage:
    from core.storage.encryption import EncryptionService

    svc = EncryptionService(master_key="<64-hex-char-key>")
    encrypted = svc.encrypt(b"plaintext", user_id="user-123")
    decrypted = svc.decrypt(encrypted, user_id="user-123")
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

if TYPE_CHECKING:
    from pathlib import Path

# Wire format constants
_IV_LENGTH = 12  # 96-bit nonce recommended for AES-GCM
_TAG_LENGTH = 16  # 128-bit authentication tag
_KEY_LENGTH = 32  # 256-bit AES key

# HKDF context identifier -- versioned so we can rotate the derivation
# scheme in the future without ambiguity.
_HKDF_INFO = b"rendertrust-storage-v1"


class EncryptionService:
    """AES-256-GCM encryption with per-user HKDF key derivation.

    Parameters
    ----------
    master_key:
        Hex-encoded 32-byte master key (64 hex characters).
        Loaded from the ``ENCRYPTION_MASTER_KEY`` environment variable
        in production.

    Raises
    ------
    ValueError
        If *master_key* is not exactly 64 hex characters (32 bytes).
    """

    def __init__(self, master_key: str) -> None:
        try:
            raw = bytes.fromhex(master_key)
        except ValueError as exc:
            msg = "master_key must be a valid hex string"
            raise ValueError(msg) from exc

        if len(raw) != _KEY_LENGTH:
            msg = f"master_key must be {_KEY_LENGTH} bytes ({_KEY_LENGTH * 2} hex chars)"
            raise ValueError(msg)

        self._master_key = raw

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    def derive_user_key(self, user_id: str) -> bytes:
        """Derive a per-user 256-bit key via HKDF-SHA256.

        The *user_id* is used as the HKDF *salt* so that each user gets
        a cryptographically distinct key from the same master key.

        Parameters
        ----------
        user_id:
            Unique identifier for the user (e.g. UUID string).

        Returns
        -------
        bytes
            32-byte derived key.
        """
        hkdf = HKDF(
            algorithm=SHA256(),
            length=_KEY_LENGTH,
            salt=user_id.encode("utf-8"),
            info=_HKDF_INFO,
        )
        return hkdf.derive(self._master_key)

    # ------------------------------------------------------------------
    # Encrypt / decrypt
    # ------------------------------------------------------------------

    def encrypt(self, data: bytes, user_id: str) -> bytes:
        """Encrypt *data* with AES-256-GCM using a per-user derived key.

        Returns the wire-format blob:
        ``[12-byte IV][16-byte auth tag][ciphertext]``.

        A fresh random IV is generated for every call so that encrypting
        the same plaintext twice produces different ciphertext.

        Parameters
        ----------
        data:
            Plaintext bytes to encrypt.
        user_id:
            User whose derived key should be used.

        Returns
        -------
        bytes
            Encrypted blob in the wire format described above.
        """
        key = self.derive_user_key(user_id)
        iv = os.urandom(_IV_LENGTH)
        aesgcm = AESGCM(key)

        # AESGCM.encrypt returns ciphertext || tag (tag is last 16 bytes)
        ct_with_tag = aesgcm.encrypt(iv, data, None)

        # Split to place tag before ciphertext in our wire format
        ciphertext = ct_with_tag[:-_TAG_LENGTH]
        tag = ct_with_tag[-_TAG_LENGTH:]

        return iv + tag + ciphertext

    def decrypt(self, encrypted_data: bytes, user_id: str) -> bytes:
        """Decrypt a wire-format blob produced by :meth:`encrypt`.

        Parameters
        ----------
        encrypted_data:
            Wire-format blob ``[IV][tag][ciphertext]``.
        user_id:
            User whose derived key should be used.

        Returns
        -------
        bytes
            Original plaintext.

        Raises
        ------
        ValueError
            If *encrypted_data* is too short to contain the IV and tag.
        cryptography.exceptions.InvalidTag
            If the ciphertext has been tampered with or the wrong key
            is used.
        """
        min_length = _IV_LENGTH + _TAG_LENGTH
        if len(encrypted_data) < min_length:
            msg = (
                f"encrypted_data too short: expected at least {min_length} bytes, "
                f"got {len(encrypted_data)}"
            )
            raise ValueError(msg)

        iv = encrypted_data[:_IV_LENGTH]
        tag = encrypted_data[_IV_LENGTH : _IV_LENGTH + _TAG_LENGTH]
        ciphertext = encrypted_data[_IV_LENGTH + _TAG_LENGTH :]

        key = self.derive_user_key(user_id)
        aesgcm = AESGCM(key)

        # Reconstruct the format AESGCM.decrypt expects: ciphertext || tag
        return aesgcm.decrypt(iv, ciphertext + tag, None)

    # ------------------------------------------------------------------
    # File convenience methods
    # ------------------------------------------------------------------

    def encrypt_file(self, file_path: Path, user_id: str) -> bytes:
        """Read a file from disk and return its encrypted contents.

        Parameters
        ----------
        file_path:
            Path to the plaintext file.
        user_id:
            User whose derived key should be used.

        Returns
        -------
        bytes
            Encrypted blob in wire format.
        """
        data = file_path.read_bytes()
        return self.encrypt(data, user_id)

    def decrypt_file(self, encrypted_data: bytes, user_id: str) -> bytes:
        """Decrypt a wire-format blob (convenience alias for :meth:`decrypt`).

        Parameters
        ----------
        encrypted_data:
            Wire-format blob.
        user_id:
            User whose derived key should be used.

        Returns
        -------
        bytes
            Decrypted file contents.
        """
        return self.decrypt(encrypted_data, user_id)

    # ------------------------------------------------------------------
    # Key rotation
    # ------------------------------------------------------------------

    def rotate_key(
        self,
        old_master_key: str,
        new_master_key: str,
        user_id: str,
        encrypted_data: bytes,
    ) -> bytes:
        """Re-encrypt data from an old master key to a new master key.

        This creates a temporary :class:`EncryptionService` with the old
        key to decrypt, then encrypts with the new key (which should
        match ``self``).

        Parameters
        ----------
        old_master_key:
            Hex-encoded old master key used to originally encrypt the data.
        new_master_key:
            Hex-encoded new master key to re-encrypt with.
        user_id:
            User whose derived key should be used.
        encrypted_data:
            Wire-format blob encrypted under the old key.

        Returns
        -------
        bytes
            Wire-format blob encrypted under the new key.
        """
        old_svc = EncryptionService(old_master_key)
        new_svc = EncryptionService(new_master_key)

        plaintext = old_svc.decrypt(encrypted_data, user_id)
        return new_svc.encrypt(plaintext, user_id)
