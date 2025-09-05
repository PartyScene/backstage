import httpx
import os
import logging

logger = logging.getLogger(__name__)


class VeriffClient:

    def __init__(self):
        """
        Initialize the Veriff client.

        The API key is expected to be in the environment variable ``VERIFF_API_KEY``.
        """
        self.client = httpx.AsyncClient(
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "x-auth-client": os.environ["VERIFF_API_KEY"],
            }
        )
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
            response = await self.client.post(f"{self.base_url}/sessions", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return None
