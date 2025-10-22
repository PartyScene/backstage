"""
Apple Sign In authentication utilities.

This module provides functionality to verify Apple Sign In identity tokens
by fetching Apple's public keys and validating JWT signatures.
"""

import httpx
import jwt
from jwt import PyJWKClient
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

# Apple's public keys endpoint
APPLE_PUBLIC_KEY_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"


class AppleAuthClient:
    """Client for verifying Apple Sign In identity tokens."""
    
    def __init__(self):
        """Initialize the Apple Auth client with JWK client."""
        self.jwk_client = PyJWKClient(APPLE_PUBLIC_KEY_URL)
    
    async def verify_identity_token(
        self,
        identity_token: str,
        client_id: str,
        nonce: Optional[str] = None
    ) -> Dict:
        """
        Verify Apple Sign In identity token and extract user information.
        
        Apple's identity tokens are JWTs signed with RS256 algorithm.
        We fetch Apple's public keys and verify the signature.
        
        Args:
            identity_token: The identity token from Apple Sign In
            client_id: Your app's bundle ID or service ID
            nonce: Optional nonce value for additional security
            
        Returns:
            Dictionary containing decoded token payload with user information
            
        Raises:
            jwt.InvalidTokenError: If token verification fails
            Exception: For other verification errors
            
        References:
            - https://developer.apple.com/documentation/sign_in_with_apple/sign_in_with_apple_rest_api/verifying_a_user
            - https://developer.apple.com/documentation/signinwithapplerestapi/fetch_apple_s_public_key_for_verifying_token_signature
        """
        try:
            # Get the signing key from Apple's public keys
            signing_key = self.jwk_client.get_signing_key_from_jwt(identity_token)
            
            # Verify and decode the token
            # Apple uses RS256 algorithm for signing
            decoded_token = jwt.decode(
                identity_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=client_id,
                issuer=APPLE_ISSUER,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_aud": True,
                    "verify_iss": True,
                }
            )
            
            # Verify nonce if provided
            if nonce and decoded_token.get("nonce") != nonce:
                raise ValueError("Nonce verification failed")
            
            logger.info(f"Successfully verified Apple token for user: {decoded_token.get('sub')}")
            return decoded_token
            
        except jwt.ExpiredSignatureError:
            logger.error("Apple token has expired")
            raise
        except jwt.InvalidAudienceError:
            logger.error("Invalid audience in Apple token")
            raise
        except jwt.InvalidIssuerError:
            logger.error("Invalid issuer in Apple token")
            raise
        except jwt.InvalidTokenError as e:
            logger.error(f"Invalid Apple token: {e}")
            raise
        except Exception as e:
            logger.error(f"Error verifying Apple token: {e}")
            raise
    
    async def verify_identity_token_unverified(self, identity_token: str) -> Dict:
        """
        Decode Apple identity token without verification (for testing only).
        
        WARNING: This should only be used in development/testing environments.
        In production, always use verify_identity_token().
        
        Args:
            identity_token: The identity token from Apple Sign In
            
        Returns:
            Dictionary containing decoded token payload
        """
        try:
            decoded_token = jwt.decode(
                identity_token,
                options={"verify_signature": False},
                algorithms=["RS256"]
            )
            logger.warning("Token decoded without verification - USE ONLY FOR TESTING")
            return decoded_token
        except Exception as e:
            logger.error(f"Error decoding Apple token: {e}")
            raise


async def verify_apple_token(
    identity_token: str,
    client_id: str,
    nonce: Optional[str] = None
) -> Optional[Dict]:
    """
    Convenience function to verify Apple Sign In identity token.
    
    Args:
        identity_token: The identity token from Apple Sign In
        client_id: Your app's bundle ID or service ID
        nonce: Optional nonce value for additional security
        
    Returns:
        Dictionary with user info if valid, None if invalid
    """
    try:
        client = AppleAuthClient()
        return await client.verify_identity_token(identity_token, client_id, nonce)
    except Exception as e:
        logger.error(f"Apple token verification failed: {e}")
        return None
