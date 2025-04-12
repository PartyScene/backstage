"""
Brevo Client

This module provides a client for interacting with the Brevo API.

Example
-------

.. code-block:: python

    from brevo.client import Brevo

    brevo = Brevo()

    contact = brevo.create_contact("john.doe@example.com", "John", "Doe")

Attributes
----------

.. autosummary::
    :toctree: _autosummary

    Brevo

Classes
-------

.. autoclass:: Brevo
    :members:
    :special-members: __init__
"""

import httpx
import os
import logging

logger = logging.getLogger(__name__)


class Brevo:

    def __init__(self):
        """
        Initialize the Brevo client.

        The API key is expected to be in the environment variable ``BREVO_API_KEY``.
        """
        self.client = httpx.AsyncClient(
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": os.environ["BREVO_API_KEY"],
            }
        )
        self.base_url = "https://api.brevo.com/v3"

    async def create_contact(self, email: str, first_name: str, last_name: str) -> dict:
        """
        Create a contact in Brevo.

        Parameters
        ----------
        email : str
            The email address of the contact.
        first_name : str
            The first name of the contact.
        last_name : str
            The last name of the contact.

        Returns
        -------
        dict
            The created contact.

        Raises
        ------
        Exception
            If the contact creation fails.
        """
        try:
            payload = {
                "updateEnabled": False,
                "email": email,
                "attributes": {"FNAME": first_name, "LNAME": last_name},
            }
            response = await self.client.post(f"{self.base_url}/contacts", json=payload)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to create contact: {e}")
            return None
