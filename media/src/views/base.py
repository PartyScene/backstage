from quart import current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required
from google.cloud import storage
import werkzeug.datastructures

from ..classful import route, QuartClassful

import os
import io
import werkzeug

class BaseView(QuartClassful):
    
    def __init__(self):
          self.GCP_client = storage.Client(os.getenv('GOOGLE_CLOUD_PROJECT'))
          self.bucket = self.GCP_client.bucket("partyscene")
        
      
    @route("/upload", methods=["GET", "POST"])
    @jwt_required
    async def upload(self):
        """Upload a media type to our GCP Bucket"""
        ...
        file : werkzeug.datastructures.FileStorage = (await request.files).get('file')
        blob = self.bucket.blob(file.filename)

        blob.upload_from_file(file.stream, content_type=file.content_type or "application/octet-stream", rewind=True)
        
        # uncomment this line 
        # blob.make_public() # Permissions are really messed up idk -- error : google.api_core.exceptions.BadRequest: 400 GET https://storage.googleapis.com/storage/v1/b/partyscene/o/file/acl?prettyPrint=false: Cannot get legacy ACL for an object when uniform bucket-level access is enabled. Read more at https://cloud.google.com/storage/docs/uniform-bucket-level-acces
        
        return jsonify(url = blob.media_link)