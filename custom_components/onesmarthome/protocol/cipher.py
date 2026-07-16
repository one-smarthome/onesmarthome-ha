"""AES-CBC datagram crypto with hand-rolled PKCS7 padding.

The CLU encrypts every UDP datagram with AES in CBC mode. The shared key and IV
arrive base64-encoded inside the downloaded interface. We pad/unpad by hand
rather than leaning on a library padder so the byte-for-byte behaviour matches
exactly what the controller expects.
"""

from __future__ import annotations

import base64
import logging

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_LOGGER = logging.getLogger(__name__)

_BLOCK = 16
_VALID_KEY_SIZES = (16, 24, 32)


class DatagramCipher:
    """Encrypts and decrypts single CLU datagrams.

    Construction never raises: if the key material is unusable the instance is
    left :pyattr:`usable` is False and both operations return ``None``, letting
    the caller degrade gracefully instead of crashing integration setup.
    """

    def __init__(self, key_b64: str, iv_b64: str) -> None:
        self._cipher: Cipher | None = None
        try:
            key = base64.b64decode(key_b64)
            iv = base64.b64decode(iv_b64)
        except (ValueError, TypeError) as err:
            _LOGGER.error("Could not base64-decode key/IV: %s", err)
            return

        if len(key) not in _VALID_KEY_SIZES or len(iv) != _BLOCK:
            _LOGGER.error(
                "Unusable key/IV sizes: key=%d bytes, iv=%d bytes", len(key), len(iv)
            )
            return

        self._cipher = Cipher(algorithms.AES(key), modes.CBC(iv))

    @property
    def usable(self) -> bool:
        return self._cipher is not None

    def encrypt(self, plaintext: bytes) -> bytes | None:
        if self._cipher is None:
            return None
        try:
            padded = self._pad(plaintext)
            enc = self._cipher.encryptor()
            return enc.update(padded) + enc.finalize()
        except Exception as err:  # noqa: BLE001 - never let crypto crash the loop
            _LOGGER.error("Encrypt failed: %s", err)
            return None

    def decrypt(self, ciphertext: bytes) -> bytes | None:
        if self._cipher is None:
            return None
        try:
            dec = self._cipher.decryptor()
            padded = dec.update(ciphertext) + dec.finalize()
            return self._unpad(padded)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Decrypt failed: %s", err)
            return None

    @staticmethod
    def _pad(data: bytes) -> bytes:
        # PKCS7: append N bytes of value N, where N fills the block. When the
        # input is already aligned a whole extra block is added, as required.
        n = _BLOCK - (len(data) % _BLOCK)
        return data + bytes([n]) * n

    @staticmethod
    def _unpad(data: bytes) -> bytes:
        if not data:
            raise ValueError("empty plaintext")
        n = data[-1]
        # A valid pad length is 1..BLOCK and every trailing byte must equal it.
        if n < 1 or n > _BLOCK or data[-n:] != bytes([n]) * n:
            raise ValueError("bad PKCS7 padding")
        return data[:-n]
