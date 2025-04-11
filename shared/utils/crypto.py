
##

from cryptography.hazmat.primitives import ciphers
import os

class SlimCipher(ciphers.Cipher):
    """A two-way cipher class for encryption and decryption that dynamically loads the appropriate algorithms from the cryptography library.

    This class is designed to be as lightweight as possible, with as few dependencies as possible, while still being able to handle both encryption and decryption.

    Parameters:
        key (bytes): The key to use for encryption and decryption. If not provided, a random one will be generated.
        iv (bytes): The initialization vector to use for encryption and decryption. If not provided, a random one will be generated.
    """

    def __init__(self, *args, **kwargs):
        """
        A slim, dynamic, two-way cipher class that handles encryption and decryption.
        
        Parameters:
            key (bytes): The key to use for encryption and decryption. If not provided, a random one will be generated.
            iv (bytes): The initialization vector to use for encryption and decryption. If not provided, a random one will be generated.
        
        Attributes:
            key (bytes): The key to use for encryption and decryption.
            iv (bytes): The initialization vector to use for encryption and decryption.
        
        Methods:
            encrypt(data: bytes) -> bytes: Encrypt the given data.
            decrypt(data: bytes) -> bytes: Decrypt the given data.
        """
        self.key = os.urandom(32) or kwargs.get('key')
        self.iv = os.urandom(16) or kwargs.get('iv')
        
        super(SlimCipher, self).__init__(ciphers.algorithms.AES(self.key), ciphers.modes.CBC(self.iv), *args, **kwargs)
    
    def encrypt(self, data: bytes) -> bytes:
        """This encrypt method will be responsible for taking a user email, encrypting it and returning the encrypted data, 
        associated key and initialization vector so that the data can be decrypted later and stored in the database.

        Args:
            data (_type_): _description_
        """
        ct = self.encryptor().update(data) + self.encryptor().finalize()
        return ct, self.key, self.iv
    
    def decrypt(self, ct: bytes) -> bytes:
        """This decrypt method will be responsible for taking the encrypted data, key and initialization vector, 
        decrypting it and returning the original data.

        Args:
            ct (_type_): _description_
        """
        decryptor = self.decryptor()
        return decryptor.update(ct) + decryptor.finalize()