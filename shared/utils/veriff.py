import rusty_req
import orjson as json
import os
import logging
from shared.utils import parse_rusty_req_response

logger = logging.getLogger(__name__)


class VeriffClient:

    def __init__(self):
        """
        Initialize the Veriff client.

        The API key is expected to be in the environment variable ``VERIFF_API_KEY``.
        """
        self.headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-auth-client": os.environ["VERIFF_API_KEY"],
        }
        self.base_url = os.environ["VERIFF_API_URL"]

    async def create_session(self, user_id: str):
        """
        Create a veriff Session

        Returns
        -------
        dict
            The created session response.

        Raises
        ------
        Exception
            If the session creation fails.
        """
        try:
            payload = {"verification": {"vendorData": user_id, "endUserId": user_id}}
            response = await rusty_req.fetch_single(
                url=f"{self.base_url}/sessions",
                method="POST",
                headers=self.headers,
                params=payload,
                timeout=10.0,
            )
            
            return parse_rusty_req_response(response, expected_status=(200, 201))
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return None
