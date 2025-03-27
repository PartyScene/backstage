from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime
from aiocache import cached


import io
from importlib import util
from PIL import Image
import requests
from contextlib import asynccontextmanager

from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue

class RMQBroker(RabbitBroker):

    def __init__(self, app, *args, **kwargs):
        self.RABBITMQ_MEDIA_QUEUE = RabbitQueue(os.environ["RABBITMQ_MEDIA_QUEUE"])
        self.RABBITMQ_R18E_QUEUE = RabbitQueue(os.environ["RABBITMQ_R18E_QUEUE"])

        self.__vector_database = app.conn
        super().__init__(url = os.environ["RABBITMQ_URI"], *args, **kwargs)


        if app.microservice_instance == "MEDIA":
            import obstore as obs
            from obstore.store import GCSStore
            self.OBS_STORE = GCSStore(os.environ["GCS_BUCKET_NAME"])

            @self.subscriber(self.RABBITMQ_MEDIA_QUEUE)
            async def handle_media_upload(message):
                await self.upload_to_bucket(message.headers.get("filename"), message.body)

        if app.microservice_instance == "R18E":
            @self.subscriber(self.RABBITMQ_R18E_QUEUE)
            async def handle_r18e(message):
                await self.process_r18e_event(message)

        if util.find_spec("torch"):
            import torch
            from transformers import ViTImageProcessor, ViTModel
            self.processor = ViTImageProcessor.from_pretrained('google/vit-base-patch16-224-in21k')
            self.model = ViTModel.from_pretrained('google/vit-base-patch16-224-in21k', output_hidden_states=True)
        
        self.start()
    
    async def upload_to_bucket(self, filename, image_bytes: bytes):
        await obs.put_async(self.OBS_STORE, filename, image_bytes)
    
    async def _publish_r18e(self, event: str, file: bytes):
        await self.publisher(self.RABBITMQ_R18E_QUEUE).publish(
            RabbitMessage(
                headers={
                    "event": event,
                },
                body=file
            )
        )
    
    async def _publish_media(self, data: dict, file: bytes):
        """
        This method publishes a message to the media queue.
        Make sure to pass the following data in the dictionary:
            - filename
            - event
            - creator 
            - type
        
        Args:
            data (dict): Dictionary containing the data to be published
            file (bytes): File to be published
        """
        await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(
            file,
            headers={
                "filename": data.get("filename"),
            }
        )

    async def process_r18e_event(self, message: RabbitMessage):
        
        image = Image.open(io.BytesIO(message.body)).convert('RGB')

        inputs = self.processor(images=image, return_tensors="pt")

        with torch.no_grad():
            outputs = self.model(**inputs)

            # Retrieve all hidden states
            hidden_states = outputs.hidden_states  # Tuple of (num_layers+1, batch, seq_len, hidden_dim)

            # Get the last 4 hidden states
            last_4_layers = hidden_states[-4:]  # Last 4 layers

            # Option 1: Average over last 4 layers
            embedding = torch.stack(last_4_layers).mean(dim=0)  # (batch, seq_len, hidden_dim)
        
        resp = await self.__vector_database.store_embedding(message.headers.get("event"), embedding.tolist())
        return resp