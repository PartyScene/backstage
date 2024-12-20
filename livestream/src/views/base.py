import datetime, aioipfs
import random

import os

from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage

from livestream.src.lib.livestream import LiveStream

from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    
    app = app
    livestream = LiveStream(app.db, app.logger)

    @route("/<event_id>", methods=["GET", "POST"])
    async def index(self, event_id):
        """
        Flow: Create a Stream -> Create Input -> Record Input -> Store Output -> Connect to Output
        API Endpoint to create a livestream input using GCP Livestream API.
        """
        
        if request.method == "POST":
            stream_create_resp = await self.livestream.start_stream(event_id)
            if stream_create_resp:
                stream_info = await self.livestream.get_stream(event_id)
                return jsonify(stream_info), 200
            
        elif request.method == "GET":
            stream_info = await self.livestream.get_stream(event_id)
            return jsonify(stream_info), 200