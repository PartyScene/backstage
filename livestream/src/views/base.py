import datetime, aioipfs
import random

import os

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage

from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    app = app
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("LOCATION")
    client = LivestreamServiceClient()

    @route("/streams/create", methods=["GET", "POST"])
    async def create(self):
        """
        Flow: Create a Stream -> Create Input -> Record Input -> Store Output -> Connect to Output
        API Endpoint to create a livestream input using GCP Livestream API.
        Request JSON format:
        {
            "project_id": "your-project-id",
            "location": "us-central1",
            "input_id": "unique-input-id"
        }
        """
        try:
            # Parse JSON request
            data = await request.get_json()
            input_id = data["input_id"]

            # Parent resource path
            parent = f"projects/{self.project_id}/locations/{self.location}"

            # Define the input configuration
            input_config = Input(type_="RTMP_PUSH")

            # Create input via LivestreamServiceClient
            operation = self.client.create_input(parent=parent, input=input_config, input_id=input_id)
            response = operation.result(900)  # Wait for the operation to complete (900 seconds)

            # Return success response
            return jsonify({"message": "Input created successfully", "input_name": response.name})

        except Exception as e:
            # Handle and return errors
            return jsonify({"error": str(e)}), 500