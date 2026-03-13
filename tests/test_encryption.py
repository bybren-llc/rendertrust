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

"""Tests for core.storage.encryption -- AES-256-GCM data-at-rest encryption.

Covers:
- Encrypt/decrypt round-trip
- Per-user key isolation
- Wrong master key fails decryption
- Tampered ciphertext detection (GCM authentication)
- Empty data encryption
- Large data encryption (1 MB+)
- Key derivation determinism
- Key rotation
- IV uniqueness (same plaintext -> different ciphertext)
- Wire format structure validation
- Invalid master key rejection
- Encrypted data too short
- File encrypt/decrypt convenience methods
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from core.storage.encryption import EncryptionService

# A valid 32-byte (64 hex char) master key for testing.
TEST_MASTER_KEY = "a" * 64

# A second master key for cross-key tests.
ALT_MASTER_KEY = "b" * 64

TEST_USER_A = "user-aaa-111"
TEST_USER_B = "user-bbb-222"


@pytest.fixture
def svc() -> EncryptionService:
    """Return an EncryptionService with the test master key."""
    return EncryptionService(TEST_MASTER_KEY)


# ------------------------------------------------------------------
# 1. Encrypt / decrypt round-trip
# ------------------------------------------------------------------
class TestEncryptDecryptRoundTrip:
    """Basic encrypt-then-decrypt produces original plaintext."""

    def test_round_trip(self, svc: EncryptionService) -> None:
        plaintext = b"hello, rendertrust!"
        encrypted = svc.encrypt(plaintext, TEST_USER_A)
        decrypted = svc.decrypt(encrypted, TEST_USER_A)
        assert decrypted == plaintext

    def test_round_trip_binary_data(self, svc: EncryptionService) -> None:
        """Ensure arbitrary binary data (null bytes, high bytes) survives."""
        plaintext = bytes(range(256)) * 4
        encrypted = svc.encrypt(plaintext, TEST_USER_A)
        decrypted = svc.decrypt(encrypted, TEST_USER_A)
        assert decrypted == plaintext


# ------------------------------------------------------------------
# 2. Per-user key isolation
# ------------------------------------------------------------------
class TestPerUserKeyIsolation:
    """User A's ciphertext cannot be decrypted by user B's key."""

    def test_cross_user_decrypt_fails(self, svc: EncryptionService) -> None:
        plaintext = b"secret payload"
        encrypted = svc.encrypt(plaintext, TEST_USER_A)
        with pytest.raises(InvalidTag):
            svc.decrypt(encrypted, TEST_USER_B)


# ------------------------------------------------------------------
# 3. Wrong master key fails
# ------------------------------------------------------------------
class TestWrongMasterKey:
    """Ciphertext from one master key cannot be decrypted with another."""

    def test_wrong_master_key(self) -> None:
        svc_a = EncryptionService(TEST_MASTER_KEY)
        svc_b = EncryptionService(ALT_MASTER_KEY)

        plaintext = b"cross-key test"
        encrypted = svc_a.encrypt(plaintext, TEST_USER_A)
        with pytest.raises(InvalidTag):
            svc_b.decrypt(encrypted, TEST_USER_A)


# ------------------------------------------------------------------
# 4. Tampered ciphertext fails (GCM auth)
# ------------------------------------------------------------------
class TestTamperedCiphertext:
    """Flipping a single bit in the ciphertext is detected by GCM."""

    def test_tampered_ciphertext_raises(self, svc: EncryptionService) -> None:
        plaintext = b"integrity check"
        encrypted = bytearray(svc.encrypt(plaintext, TEST_USER_A))

        # Flip the last byte of the ciphertext portion
        encrypted[-1] ^= 0xFF
        with pytest.raises(InvalidTag):
            svc.decrypt(bytes(encrypted), TEST_USER_A)

    def test_tampered_tag_raises(self, svc: EncryptionService) -> None:
        """Flipping a bit in the auth tag is detected."""
        encrypted = bytearray(svc.encrypt(b"tag test", TEST_USER_A))
        # Tag starts at byte 12 (after the 12-byte IV)
        encrypted[12] ^= 0xFF
        with pytest.raises(InvalidTag):
            svc.decrypt(bytes(encrypted), TEST_USER_A)


# ------------------------------------------------------------------
# 5. Empty data encryption
# ------------------------------------------------------------------
class TestEmptyData:
    """Encrypting an empty byte string should work and round-trip."""

    def test_empty_encrypt_decrypt(self, svc: EncryptionService) -> None:
        encrypted = svc.encrypt(b"", TEST_USER_A)
        # Even empty data produces IV + tag (28 bytes minimum)
        assert len(encrypted) >= 28
        decrypted = svc.decrypt(encrypted, TEST_USER_A)
        assert decrypted == b""


# ------------------------------------------------------------------
# 6. Large data encryption (1 MB+)
# ------------------------------------------------------------------
class TestLargeData:
    """Encryption handles large payloads without error."""

    def test_one_megabyte(self, svc: EncryptionService) -> None:
        plaintext = os.urandom(1024 * 1024)  # 1 MB
        encrypted = svc.encrypt(plaintext, TEST_USER_A)
        decrypted = svc.decrypt(encrypted, TEST_USER_A)
        assert decrypted == plaintext


# ------------------------------------------------------------------
# 7. Key derivation determinism
# ------------------------------------------------------------------
class TestKeyDerivationDeterminism:
    """Same master key + user_id always produces the same derived key."""

    def test_deterministic(self, svc: EncryptionService) -> None:
        key1 = svc.derive_user_key(TEST_USER_A)
        key2 = svc.derive_user_key(TEST_USER_A)
        assert key1 == key2
        assert len(key1) == 32  # 256-bit key

    def test_different_users_different_keys(self, svc: EncryptionService) -> None:
        key_a = svc.derive_user_key(TEST_USER_A)
        key_b = svc.derive_user_key(TEST_USER_B)
        assert key_a != key_b


# ------------------------------------------------------------------
# 8. Key rotation
# ------------------------------------------------------------------
class TestKeyRotation:
    """Re-encrypting from old key to new key preserves plaintext."""

    def test_rotate_key(self) -> None:
        old_svc = EncryptionService(TEST_MASTER_KEY)
        new_svc = EncryptionService(ALT_MASTER_KEY)

        plaintext = b"rotate me"
        encrypted_old = old_svc.encrypt(plaintext, TEST_USER_A)

        # Rotate: decrypt with old key, re-encrypt with new key
        encrypted_new = new_svc.rotate_key(
            old_master_key=TEST_MASTER_KEY,
            new_master_key=ALT_MASTER_KEY,
            user_id=TEST_USER_A,
            encrypted_data=encrypted_old,
        )

        # New ciphertext should decrypt with the new key
        decrypted = new_svc.decrypt(encrypted_new, TEST_USER_A)
        assert decrypted == plaintext

        # Old service should NOT be able to decrypt the rotated ciphertext
        with pytest.raises(InvalidTag):
            old_svc.decrypt(encrypted_new, TEST_USER_A)


# ------------------------------------------------------------------
# 9. IV uniqueness
# ------------------------------------------------------------------
class TestIVUniqueness:
    """Encrypting the same plaintext twice produces different ciphertext."""

    def test_different_ciphertext_each_time(self, svc: EncryptionService) -> None:
        plaintext = b"same input"
        enc1 = svc.encrypt(plaintext, TEST_USER_A)
        enc2 = svc.encrypt(plaintext, TEST_USER_A)
        assert enc1 != enc2

        # But both decrypt to the same plaintext
        assert svc.decrypt(enc1, TEST_USER_A) == plaintext
        assert svc.decrypt(enc2, TEST_USER_A) == plaintext


# ------------------------------------------------------------------
# 10. Wire format structure
# ------------------------------------------------------------------
class TestWireFormat:
    """Verify the wire format is [12-byte IV][16-byte tag][ciphertext]."""

    def test_wire_format_length(self, svc: EncryptionService) -> None:
        plaintext = b"wire format check"
        encrypted = svc.encrypt(plaintext, TEST_USER_A)
        # Total = 12 (IV) + 16 (tag) + len(plaintext)
        expected_len = 12 + 16 + len(plaintext)
        assert len(encrypted) == expected_len


# ------------------------------------------------------------------
# 11. Invalid master key
# ------------------------------------------------------------------
class TestInvalidMasterKey:
    """Reject master keys that are too short, too long, or non-hex."""

    def test_too_short(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            EncryptionService("aa" * 15)  # 15 bytes

    def test_too_long(self) -> None:
        with pytest.raises(ValueError, match="32 bytes"):
            EncryptionService("aa" * 33)  # 33 bytes

    def test_non_hex(self) -> None:
        with pytest.raises(ValueError, match="valid hex"):
            EncryptionService("zz" * 32)


# ------------------------------------------------------------------
# 12. Encrypted data too short
# ------------------------------------------------------------------
class TestEncryptedDataTooShort:
    """Reject encrypted data shorter than IV + tag (28 bytes)."""

    def test_too_short_raises(self, svc: EncryptionService) -> None:
        with pytest.raises(ValueError, match="too short"):
            svc.decrypt(b"\x00" * 27, TEST_USER_A)

    def test_exactly_minimum_ok(self, svc: EncryptionService) -> None:
        """28 bytes (IV + tag + empty ciphertext) should attempt decryption."""
        # This will fail with InvalidTag (wrong tag), not ValueError
        with pytest.raises(InvalidTag):
            svc.decrypt(b"\x00" * 28, TEST_USER_A)


# ------------------------------------------------------------------
# 13. File convenience methods
# ------------------------------------------------------------------
class TestFileConvenience:
    """encrypt_file / decrypt_file round-trip via Path."""

    def test_file_round_trip(self, svc: EncryptionService) -> None:
        plaintext = b"file contents for testing"
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(plaintext)
            tmp_path = Path(tmp.name)

        try:
            encrypted = svc.encrypt_file(tmp_path, TEST_USER_A)
            decrypted = svc.decrypt_file(encrypted, TEST_USER_A)
            assert decrypted == plaintext
        finally:
            tmp_path.unlink()
