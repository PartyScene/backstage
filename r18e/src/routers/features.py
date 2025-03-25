from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime
from aiocache import cached



import torch

from transformers import ViTImageProcessor, ViTModel
from PIL import Image
import requests
from contextlib import asynccontextmanager

from ..internals.connector import R18E


class BaseView(QuartClassful):

    # from transformers import AutoImageProcessor, ResNetForImageClassification

    # image_processor = AutoImageProcessor.from_pretrained("microsoft/resnet-50")
    # model = ResNetForImageClassification.from_pretrained("microsoft/resnet-50")

    # inputs = image_processor(image, return_tensors="pt")

    def __init__(self) -> None:
        self.processor = ViTImageProcessor.from_pretrained('google/vit-base-patch16-224-in21k')
        self.model = ViTModel.from_pretrained('google/vit-base-patch16-224-in21k', output_hidden_states=True)
        self.__vector_database : R18E = app.conn

    @route("/", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def index(self):
        return await self.healthcheck()
        
    @route("/posts/health", methods=["GET"])
    @cached(ttl=60 * 60 * 72)
    async def healthcheck(self):
        return jsonify({"status": "healthy"}), HTTPStatus.OK

    @route("/features/extract", methods=["POST"])
    async def extract_features(self):
        """

        Args:
            event_id (str): Event ID
            file (UploadFile): Image file
        """
        event_id = request.args.get("event_id", None)
        if not event_id:
            return jsonify({"error": "Event ID is required"}), HTTPStatus.BAD_REQUEST

        file : FileStorage = (await request.files).get("file")
        if not file:
            return jsonify({"error": "File is required"}), HTTPStatus.BAD_REQUEST

        file.stream.seek(0)

        image = Image.open(file.stream)

        inputs = self.processor(images=image, return_tensors="pt")

        with torch.no_grad():
            outputs = self.model(**inputs)

            # Retrieve all hidden states
            hidden_states = outputs.hidden_states  # Tuple of (num_layers+1, batch, seq_len, hidden_dim)

            # Get the last 4 hidden states
            last_4_layers = hidden_states[-4:]  # Last 4 layers

            # Option 1: Average over last 4 layers
            embedding = torch.stack(last_4_layers).mean(dim=0)  # (batch, seq_len, hidden_dim)
        
        resp = await self.__vector_database.store_embedding(event_id, embedding.tolist())
        return jsonify(resp), HTTPStatus.OK