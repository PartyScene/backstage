import base64
import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
import os
import argparse
from urllib.parse import parse_qs, urlsplit

# --- Configuration (from Step 2) ---
CDN_SIGNING_KEY_NAME = os.environ.get("CDN_SIGNING_KEY_NAME") # "my-cdn-signing-key" # The name you gave in the console
CDN_SIGNING_SECRET = os.environ.get("CDN_SIGNING_SECRET") # The secret you copied

# --- Function to generate CDN Signed URL ---
def generate_cdn_signed_url(base_url: str, object_path: str, expiration_time: timedelta) -> str:
    """Generates a Cloud CDN signed URL."""
    
    # Construct the URL path for signing
    # The URL should be relative to your load balancer's IP/hostname
    full_url = f"{base_url}{object_path}"
    try:
        stripped_url = full_url.strip()
        parsed_url = urlsplit(stripped_url)
        query_params = parse_qs(parsed_url.query, keep_blank_values=True)
        # epoch = datetime.fromtimestamp(0, timezone.utc)
        expiration_timestamp = int(time.time() + expiration_time.total_seconds()) # int((expiration_time - epoch).total_seconds()) # 
        decoded_key = base64.urlsafe_b64decode(CDN_SIGNING_SECRET)

        url_to_sign = f"{stripped_url}{'&' if query_params else '?'}Expires={expiration_timestamp}&KeyName={CDN_SIGNING_KEY_NAME}"

        digest = hmac.new(decoded_key, url_to_sign.encode("utf-8"), hashlib.sha1).digest()
        signature = base64.urlsafe_b64encode(digest).decode("utf-8")

        return f"{url_to_sign}&Signature={signature}"
    except Exception as e:
        raise e