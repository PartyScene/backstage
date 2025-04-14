from cryptography.hazmat.primitives import ciphers, padding
from cryptography.hazmat.backends import default_backend
from .secrets import SecretManager

import os


class AsyncEnvelopeCipherService:

    async def encrypt(self, plaintext: bytes) -> dict:
        kek = await SecretManager().get_kek_secret()
        return EnvelopeCipher(kek).encrypt(plaintext)

    async def decrypt(
        self,
        encrypted_data: bytes,
        encrypted_dek: bytes,
        data_initialization_vector: bytes,
        decryption_key_initialization_vector: bytes,
    ) -> bytes:
        kek = await SecretManager().get_kek_secret()
        return EnvelopeCipher(kek).decrypt(
            encrypted_data,
            encrypted_dek,
            data_initialization_vector,
            decryption_key_initialization_vector,
        )


class EnvelopeCipher:
    """
    A secure two-way encryption class implementing envelope encryption.

    Envelope encryption is a security pattern in which a Data Encryption Key (DEK)
    is randomly generated for encrypting actual data, while the DEK itself is
    encrypted using a Key Encryption Key (KEK). The KEK should be securely stored
    in a secret manager (e.g., Google Cloud Secret Manager).

    Attributes:
        kek (bytes): The Key Encryption Key (KEK) used to encrypt and decrypt the DEK.

    Methods:
        encrypt(plaintext: bytes) -> dict:
            Encrypts the given plaintext using a random DEK and returns the encrypted data,
            the encrypted DEK, and their respective IVs.

        decrypt(encrypted_data: bytes, encrypted_dek: bytes, iv_data: bytes, iv_kek: bytes) -> bytes:
            Decrypts the encrypted DEK with the KEK and then uses it to decrypt the data.
    """

    def __init__(self, kek: bytes):
        assert isinstance(kek, bytes) and len(kek) in [
            16,
            24,
            32,
        ], "KEK must be a valid AES key"
        self.kek = kek
        self.backend = default_backend()

    def _get_cipher(self, key: bytes, iv: bytes):
        return ciphers.Cipher(
            ciphers.algorithms.AES(key), ciphers.modes.CBC(iv), backend=self.backend
        )

    def encrypt(self, plaintext: bytes):
        """
        Encrypts the plaintext using a randomly generated DEK, which is then encrypted using the KEK.

        Args:
            plaintext (bytes): The raw data to be encrypted.

        Returns:
            dict: Contains:
                - encrypted_data (bytes): The AES-encrypted data.
                - encrypted_dek (bytes): The AES-encrypted DEK using the KEK.
                - iv_data (bytes): IV used for encrypting the data.
                - iv_kek (bytes): IV used for encrypting the DEK.
        """
        decryption_key = os.urandom(32)
        data_initialization_vector = os.urandom(16)

        # Pad the data
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(plaintext) + padder.finalize()

        # Encrypt the data
        cipher_context = self._get_cipher(
            decryption_key, data_initialization_vector
        ).encryptor()
        encrypted_data = cipher_context.update(padded_data) + cipher_context.finalize()

        # Encrypt the DEK
        decryption_key_initialization_vector = os.urandom(16)
        cipher_context = self._get_cipher(
            self.kek, decryption_key_initialization_vector
        ).encryptor()

        padder = padding.PKCS7(128).padder()
        padded_dek = padder.update(decryption_key) + padder.finalize()
        encrypted_decryption_key = (
            cipher_context.update(padded_dek) + cipher_context.finalize()
        )

        return {
            "encrypted_data": encrypted_data,
            "encrypted_decryption_key": encrypted_decryption_key,
            "data_initialization_vector": data_initialization_vector,
            "decryption_key_initialization_vector": decryption_key_initialization_vector,
        }

    def decrypt(
        self,
        encrypted_data: bytes,
        encrypted_dek: bytes,
        data_initialization_vector: bytes,
        decryption_key_initialization_vector: bytes,
    ):
        """
        Decrypts the provided encrypted data using envelope decryption.

        Args:
            encrypted_data (bytes): The AES-encrypted data.
            encrypted_dek (bytes): The AES-encrypted DEK.
            iv_data (bytes): IV used during data encryption.
            iv_kek (bytes): IV used during DEK encryption.

        Returns:
            bytes: The original plaintext.
        """
        cipher_kek = self._get_cipher(
            self.kek, decryption_key_initialization_vector
        ).decryptor()
        padded_dek = cipher_kek.update(encrypted_dek) + cipher_kek.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        dek = unpadder.update(padded_dek) + unpadder.finalize()

        cipher_data = self._get_cipher(dek, data_initialization_vector).decryptor()
        padded_data = cipher_data.update(encrypted_data) + cipher_data.finalize()

        unpadder = padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded_data) + unpadder.finalize()
        return plaintext
