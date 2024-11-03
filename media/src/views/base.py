from quart import current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required
from google.cloud import storage

from ..classful import route, QuartClassful


class BaseView(QuartClassful):
    
    def __init__(self):
          self.GCP_client = storage.Client()
          self.bucket = self.GCP_client.bucket("partyscene")
      
    @route("/upload", methods=["GET", "POST"])
    @jwt_required
    async def index(self):
        """Upload a media type to our GCP Bucket"""
        ...
        for file in (await request.files):
            blob = self.bucket.blob(file.filename)
            blob.upload_from_string(file.read())
        
        return jsonify({'url': blob.public_url})