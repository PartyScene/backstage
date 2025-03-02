from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from shared.workers import create_livestream_client

from http import HTTPStatus
from shared.classful import route, QuartClassful


class BaseView(QuartClassful):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.livestream = create_livestream_client(app.db, app.logger)

    @route("/<event_id>", methods=["GET"])
    async def get_livestream(self, event_id):
        try:
            stream_info = await self.livestream.get_stream(event_id)
            return jsonify(stream_info), HTTPStatus.OK
        except:
            return (
                jsonify({"error": "Failed to get livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    @route("/<event_id>", methods=["POST"])
    async def create_livestream(self, event_id):  # Renamed from index to manage_stream
        """
        Flow: Create a Stream -> Create Input -> Record Input -> Store Output -> Connect to Output
        API Endpoint to create a livestream input using GCP Livestream API.
        """

        try:
            stream_create_resp = await self.livestream.start_stream(event_id)
            if stream_create_resp:
                stream_info = await self.livestream.get_stream(event_id)
                return jsonify(stream_info), HTTPStatus.CREATED
        except:
            return (
                jsonify({"error": "Failed to create livestream"}),
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
