from pprint import pprint
from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage

from ..lib.livestream import LiveStream

from classful import route, QuartClassful


class BaseView(QuartClassful):
    
    route_base = "/livestream/"  # Add namespace for routes
    
    @classmethod
    def register(self, app):
        self.livestream = LiveStream(app.db, app.logger)
        super().register(app)

    @route("/<event_id>", methods=["GET", "POST"])
    async def manage_stream(self, event_id):  # Renamed from index to manage_stream
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