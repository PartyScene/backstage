# Apple Sign In Testing Guide

Complete guide for testing Apple Sign In implementation in PartyScene.

## Table of Contents

1. [Backend Unit Tests](#1-backend-unit-tests)
2. [Local Development Testing](#2-local-development-testing)
3. [React Native App Testing](#3-react-native-app-testing)
4. [End-to-End Testing](#4-end-to-end-testing)
5. [Production Testing](#5-production-testing)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. Backend Unit Tests

### Run Automated Tests

```bash
# Activate virtual environment
& c:/Users/User/Documents/Projects/sites/.venv/Scripts/Activate.ps1

# Run Apple SSO tests only
pytest tests/auth/test_apple_sso.py -v

# Run all auth tests
pytest tests/auth/ -v

# Run with coverage
pytest tests/auth/test_apple_sso.py --cov=auth.src.views --cov-report=html
```

### What Gets Tested

- ✅ New user registration flow
- ✅ Existing user login flow
- ✅ Missing token validation
- ✅ Invalid token handling
- ✅ Unverified email rejection
- ✅ Private relay email support
- ✅ Token expiration handling

---

## 2. Local Development Testing

### Option A: Manual Test Script

Run the manual testing suite:

```bash
# Make sure your auth service is running
python -m tests.auth.manual_test_apple
```

This script tests:
- New user registration with mock tokens
- Existing user login
- Invalid token rejection
- Missing token validation
- Authenticated requests

### Option B: Development Mode (Skip Verification)

For local testing without real Apple tokens:

**1. Enable Dev Mode:**

```bash
# Add to your .env file
APPLE_DEV_MODE=true
APPLE_CLIENT_ID=com.scenesllc.partyscene
```

**2. Use curl or Postman:**

```bash
# Test new user registration
curl -X POST http://localhost:8080/auth/apple \
  -H "Content-Type: application/json" \
  -d '{
    "identity_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2FwcGxlaWQuYXBwbGUuY29tIiwic3ViIjoiMDAxMjM0LnRlc3QxMjM0NS42Nzg5IiwiZW1haWwiOiJ0ZXN0QHByaXZhdGVyZWxheS5hcHBsZWlkLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjoidHJ1ZSJ9.fake_signature",
    "user": {
      "name": {
        "firstName": "Test",
        "lastName": "User"
      },
      "email": "test@privaterelay.appleid.com"
    }
  }'

# Test existing user login (without user data)
curl -X POST http://localhost:8080/auth/apple \
  -H "Content-Type: application/json" \
  -d '{
    "identity_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJodHRwczovL2FwcGxlaWQuYXBwbGUuY29tIiwic3ViIjoiMDAxMjM0LnRlc3QxMjM0NS42Nzg5IiwiZW1haWwiOiJ0ZXN0QHByaXZhdGVyZWxheS5hcHBsZWlkLmNvbSIsImVtYWlsX3ZlcmlmaWVkIjoidHJ1ZSJ9.fake_signature"
  }'
```

**⚠️ WARNING:** Never enable `APPLE_DEV_MODE` in production!

### Option C: Postman Collection

Import this collection for testing:

```json
{
  "info": {
    "name": "Apple Sign In Tests",
    "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
  },
  "item": [
    {
      "name": "Apple Sign In - New User",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Content-Type",
            "value": "application/json"
          }
        ],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"identity_token\": \"{{apple_token}}\",\n  \"user\": {\n    \"name\": {\n      \"firstName\": \"Test\",\n      \"lastName\": \"User\"\n    },\n    \"email\": \"test@privaterelay.appleid.com\"\n  }\n}"
        },
        "url": {
          "raw": "{{base_url}}/auth/apple",
          "host": ["{{base_url}}"],
          "path": ["auth", "apple"]
        }
      }
    },
    {
      "name": "Apple Sign In - Existing User",
      "request": {
        "method": "POST",
        "header": [
          {
            "key": "Content-Type",
            "value": "application/json"
          }
        ],
        "body": {
          "mode": "raw",
          "raw": "{\n  \"identity_token\": \"{{apple_token}}\"\n}"
        },
        "url": {
          "raw": "{{base_url}}/auth/apple",
          "host": ["{{base_url}}"],
          "path": ["auth", "apple"]
        }
      }
    }
  ]
}
```

---

## 3. React Native App Testing

### iOS Simulator Testing

**⚠️ Note:** Apple Sign In may not work on all simulators. Real device testing is recommended.

### Real Device Testing (Recommended)

**1. Install TestFlight Build:**

```bash
# Build and deploy to TestFlight
cd your-react-native-app
eas build --platform ios --profile preview
```

**2. Enable Apple Sign In:**

- Ensure capability is enabled in Xcode
- Bundle ID matches APPLE_CLIENT_ID on backend
- App is signed with valid provisioning profile

**3. Test Flow:**

```
1. Launch app on device
2. Tap "Sign in with Apple" button
3. Authenticate with Face ID/Touch ID
4. Verify redirect back to app
5. Check access token received
6. Make authenticated API request
```

### Debug Logs in React Native

Add detailed logging to debug:

```typescript
const handleAppleSignIn = async () => {
  try {
    console.log('🍎 Starting Apple Sign In...');
    
    const appleAuthRequestResponse = await appleAuth.performRequest({
      requestedOperation: AppleAuthRequestOperation.LOGIN,
      requestedScopes: [
        AppleAuthRequestScope.EMAIL,
        AppleAuthRequestScope.FULL_NAME,
      ],
    });

    console.log('🍎 Apple Response:', {
      user: appleAuthRequestResponse.user,
      email: appleAuthRequestResponse.email,
      fullName: appleAuthRequestResponse.fullName,
      identityToken: appleAuthRequestResponse.identityToken?.substring(0, 50) + '...',
    });

    const { identityToken, user, email, fullName } = appleAuthRequestResponse;

    if (!identityToken) {
      throw new Error('No identity token received from Apple');
    }

    // Build payload
    const payload = {
      identity_token: identityToken,
      user: user && fullName ? {
        name: {
          firstName: fullName.givenName || '',
          lastName: fullName.familyName || '',
        },
        email: email || '',
      } : undefined,
    };

    console.log('📤 Sending to backend:', {
      hasToken: !!payload.identity_token,
      hasUserData: !!payload.user,
    });

    const response = await fetch(`${API_URL}/auth/apple`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });

    console.log('📥 Backend response status:', response.status);

    const data = await response.json();
    console.log('📥 Backend response data:', data);

    if (!response.ok) {
      throw new Error(data.message || 'Authentication failed');
    }

    console.log('✅ Sign in successful!');
    return data;

  } catch (error) {
    console.error('❌ Apple Sign In error:', error);
    throw error;
  }
};
```

### React Native Debugger

Use Flipper or React Native Debugger to inspect:

- Network requests
- Token format
- Response data
- Error messages

---

## 4. End-to-End Testing

### Complete Flow Test

**1. Start Backend:**

```bash
cd auth
python -m src.main
```

**2. Start React Native App:**

```bash
cd mobile-app
npm start
```

**3. Test Scenarios:**

#### Scenario 1: First-Time User

```
1. User opens app
2. Taps "Sign in with Apple"
3. Apple authentication modal appears
4. User authenticates (Face ID/Touch ID)
5. User consents to share email and name
6. App receives identityToken + user info
7. App sends to POST /auth/apple
8. Backend creates new user
9. Backend returns access_token
10. App stores token securely
11. App navigates to home screen
12. User is logged in
```

#### Scenario 2: Returning User

```
1. User opens app
2. Taps "Sign in with Apple"
3. Apple authentication modal appears
4. User authenticates (Face ID/Touch ID)
5. App receives identityToken only (no user info)
6. App sends to POST /auth/apple
7. Backend finds existing user by email
8. Backend returns access_token
9. App stores token securely
10. App navigates to home screen
11. User is logged in
```

#### Scenario 3: Private Relay Email

```
1. User signs in for first time
2. User chooses "Hide My Email"
3. Apple provides @privaterelay.appleid.com email
4. Backend stores private relay email
5. User can receive emails via relay
6. Subsequent logins work with relay email
```

---

## 5. Production Testing

### Pre-Production Checklist

- [ ] `APPLE_DEV_MODE` is set to `false` or removed
- [ ] `APPLE_CLIENT_ID` matches production bundle ID
- [ ] SSL/TLS certificates are valid
- [ ] Apple Developer account verified
- [ ] Sign in with Apple capability enabled in App Store Connect
- [ ] Privacy policy updated with Apple Sign In mention

### Production Test Plan

**1. Staging Environment:**

```bash
# Test against staging backend
API_URL=https://staging-api.partyscene.app

# Use TestFlight build
# Test with multiple Apple IDs
```

**2. Monitoring:**

```bash
# Watch backend logs
kubectl logs -f deployment/auth-service -n partyscene | grep -i apple

# Check metrics
# - Sign in success rate
# - Token verification failures
# - Error rates
```

**3. Test Cases:**

- [ ] New user registration
- [ ] Existing user login
- [ ] Private relay emails
- [ ] Multiple devices same account
- [ ] Account deletion flow
- [ ] Token expiration handling
- [ ] Network error handling

---

## 6. Troubleshooting

### Common Issues

#### Issue: "Invalid audience" Error

**Cause:** `APPLE_CLIENT_ID` doesn't match bundle ID in token

**Fix:**
```bash
# Verify bundle ID matches
echo $APPLE_CLIENT_ID
# Should be: com.scenesllc.partyscene (or your bundle ID)
```

#### Issue: "Token verification failed"

**Cause:** Apple's public keys couldn't be fetched or token expired

**Fix:**
```python
# Check network connectivity to Apple
import httpx
response = httpx.get("https://appleid.apple.com/auth/keys")
print(response.json())
```

#### Issue: Email not provided after first sign in

**Cause:** Apple only provides email on first sign in

**Solution:** Store email in backend on first sign in, use `sub` (Apple user ID) for subsequent logins

#### Issue: "Email not verified" error

**Cause:** Token has `email_verified: "false"`

**Note:** This is rare with Apple Sign In. Check token payload:
```bash
# Decode token (dev mode) to inspect
python -c "import jwt; print(jwt.decode('YOUR_TOKEN', options={'verify_signature': False}))"
```

### Debug Commands

**Check backend health:**
```bash
curl http://localhost:8080/auth/health
```

**Decode Apple token (development only):**
```python
import jwt

token = "eyJraWQiOi..."
decoded = jwt.decode(token, options={"verify_signature": False})
print(decoded)
```

**Check Redis bloom filter:**
```bash
redis-cli
> BF.EXISTS email test@privaterelay.appleid.com
```

**Check database:**
```sql
-- In SurrealDB
SELECT * FROM users WHERE email = "test@privaterelay.appleid.com";
SELECT * FROM users WHERE apple_sub = "001234.test12345.6789";
```

### Getting Help

1. Check backend logs for detailed error messages
2. Enable verbose logging in React Native app
3. Use browser network tab for web testing
4. Check Apple's System Status: https://developer.apple.com/system-status/
5. Review Apple Sign In documentation: https://developer.apple.com/sign-in-with-apple/

---

## Quick Reference

### Environment Variables

```bash
# Required
APPLE_CLIENT_ID=com.scenesllc.partyscene

# Optional (development only)
APPLE_DEV_MODE=false
```

### API Endpoint

```
POST /auth/apple
Content-Type: application/json

{
  "identity_token": "string (required)",
  "user": {
    "name": {
      "firstName": "string",
      "lastName": "string"
    },
    "email": "string"
  } (optional, first sign in only)
}
```

### Response Format

```json
{
  "data": {
    "access_token": "string",
    "token_type": "bearer"
  },
  "message": "string",
  "status": "string"
}
```

### Test Commands

```bash
# Backend tests
pytest tests/auth/test_apple_sso.py -v

# Manual testing
python -m tests.auth.manual_test_apple

# Check logs
tail -f logs/auth.log | grep -i apple
```
