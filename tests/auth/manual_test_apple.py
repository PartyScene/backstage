"""
Manual testing script for Apple Sign In endpoint.

This script allows you to test the Apple Sign In endpoint without needing
a real iOS device or Apple token. It generates mock tokens for development.

Usage:
    python -m tests.auth.manual_test_apple
"""

import asyncio
import httpx
import jwt
from datetime import datetime, timedelta

# Configuration
API_URL = "http://localhost:8080"  # Change to your local dev server
APPLE_CLIENT_ID = "com.partyscene.app"  # Your bundle ID


def generate_mock_apple_token(user_id: str, email: str, include_name: bool = True) -> dict:
    """
    Generate a mock Apple identity token for testing.
    
    This creates an unsigned token that mimics Apple's structure.
    For real testing, use tokens from actual Apple Sign In.
    """
    payload = {
        "iss": "https://appleid.apple.com",
        "aud": APPLE_CLIENT_ID,
        "exp": int((datetime.now() + timedelta(hours=1)).timestamp()),
        "iat": int(datetime.now().timestamp()),
        "sub": user_id,
        "email": email,
        "email_verified": "true",
        "is_private_email": "false",
        "auth_time": int(datetime.now().timestamp()),
        "nonce_supported": True,
    }
    
    # Create an unsigned token (HS256 with empty secret for testing)
    token = jwt.encode(payload, "", algorithm="HS256")
    
    user_data = {
        "name": {
            "firstName": "Test",
            "lastName": "User"
        },
        "email": email
    } if include_name else None
    
    return {
        "identity_token": token,
        "user": user_data,
        "decoded_payload": payload
    }


async def test_new_user_registration():
    """Test registering a new user with Apple Sign In."""
    print("\n" + "="*60)
    print("TEST 1: New User Registration")
    print("="*60)
    
    user_id = "001234.test12345.6789"
    email = f"testuser_{int(datetime.now().timestamp())}@privaterelay.appleid.com"
    
    mock_data = generate_mock_apple_token(user_id, email, include_name=True)
    
    print(f"\n📧 Testing with email: {email}")
    print(f"🆔 Apple User ID: {user_id}")
    print(f"\n🔑 Generated Token (first 50 chars): {mock_data['identity_token'][:50]}...")
    
    request_body = {
        "identity_token": mock_data["identity_token"],
        "user": mock_data["user"]
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_URL}/auth/apple",
                json=request_body,
                timeout=10.0
            )
            
            print(f"\n📊 Response Status: {response.status_code}")
            print(f"📄 Response Body:")
            print(response.json())
            
            if response.status_code in [200, 201]:
                print("\n✅ SUCCESS: User registered/logged in successfully!")
                data = response.json()
                if "data" in data and "access_token" in data["data"]:
                    token = data["data"]["access_token"]
                    print(f"\n🎟️  Access Token (first 50 chars): {token[:50]}...")
                    return token
            else:
                print("\n❌ FAILED: Registration failed")
                
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
    
    return None


async def test_existing_user_login(email: str):
    """Test logging in an existing user."""
    print("\n" + "="*60)
    print("TEST 2: Existing User Login")
    print("="*60)
    
    user_id = "001234.existing999.6789"
    
    mock_data = generate_mock_apple_token(user_id, email, include_name=False)
    
    print(f"\n📧 Testing with existing email: {email}")
    print(f"🆔 Apple User ID: {user_id}")
    print("ℹ️  Note: User info not included (simulating subsequent login)")
    
    request_body = {
        "identity_token": mock_data["identity_token"]
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_URL}/auth/apple",
                json=request_body,
                timeout=10.0
            )
            
            print(f"\n📊 Response Status: {response.status_code}")
            print(f"📄 Response Body:")
            print(response.json())
            
            if response.status_code == 200:
                print("\n✅ SUCCESS: User logged in successfully!")
            else:
                print("\n⚠️  Note: May fail if using mock tokens without dev mode")
                
        except Exception as e:
            print(f"\n❌ ERROR: {e}")


async def test_invalid_token():
    """Test with an invalid token."""
    print("\n" + "="*60)
    print("TEST 3: Invalid Token")
    print("="*60)
    
    request_body = {
        "identity_token": "invalid.token.here"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_URL}/auth/apple",
                json=request_body,
                timeout=10.0
            )
            
            print(f"\n📊 Response Status: {response.status_code}")
            print(f"📄 Response Body:")
            print(response.json())
            
            if response.status_code == 401:
                print("\n✅ SUCCESS: Invalid token properly rejected!")
            else:
                print("\n⚠️  Unexpected response")
                
        except Exception as e:
            print(f"\n❌ ERROR: {e}")


async def test_missing_token():
    """Test with missing identity token."""
    print("\n" + "="*60)
    print("TEST 4: Missing Token")
    print("="*60)
    
    request_body = {}
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{API_URL}/auth/apple",
                json=request_body,
                timeout=10.0
            )
            
            print(f"\n📊 Response Status: {response.status_code}")
            print(f"📄 Response Body:")
            print(response.json())
            
            if response.status_code == 400:
                print("\n✅ SUCCESS: Missing token properly rejected!")
            else:
                print("\n⚠️  Unexpected response")
                
        except Exception as e:
            print(f"\n❌ ERROR: {e}")


async def test_authenticated_request(access_token: str):
    """Test making an authenticated request with the token."""
    print("\n" + "="*60)
    print("TEST 5: Authenticated Request")
    print("="*60)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{API_URL}/auth/health",  # or any protected endpoint
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10.0
            )
            
            print(f"\n📊 Response Status: {response.status_code}")
            print(f"📄 Response Body:")
            print(response.json())
            
            if response.status_code == 200:
                print("\n✅ SUCCESS: Authenticated request successful!")
            else:
                print("\n⚠️  Check if endpoint requires authentication")
                
        except Exception as e:
            print(f"\n❌ ERROR: {e}")


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("🍎 APPLE SIGN IN - MANUAL TESTING SUITE")
    print("="*60)
    print(f"\n🌐 API URL: {API_URL}")
    print(f"📱 Client ID: {APPLE_CLIENT_ID}")
    print("\n⚠️  IMPORTANT: These tests use mock tokens.")
    print("   For production testing, use real tokens from Apple Sign In.")
    print("   You may need to enable development mode on the backend.")
    
    # Test 1: New user registration
    access_token = await test_new_user_registration()
    
    # Wait a bit
    await asyncio.sleep(1)
    
    # Test 2: Existing user login (reuse the email from test 1)
    if access_token:
        # For this test, we'd need to extract the email from the first test
        # For now, using a generic test
        await test_existing_user_login("test@privaterelay.appleid.com")
    
    await asyncio.sleep(1)
    
    # Test 3: Invalid token
    await test_invalid_token()
    
    await asyncio.sleep(1)
    
    # Test 4: Missing token
    await test_missing_token()
    
    await asyncio.sleep(1)
    
    # Test 5: Authenticated request (if we got a token)
    if access_token:
        await test_authenticated_request(access_token)
    
    print("\n" + "="*60)
    print("✅ ALL TESTS COMPLETED")
    print("="*60)
    print("\nNext Steps:")
    print("1. Review the results above")
    print("2. Test with real Apple tokens on iOS device")
    print("3. Run pytest tests for comprehensive coverage")
    print("4. Test in production environment")


if __name__ == "__main__":
    asyncio.run(main())
