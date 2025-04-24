from quart import make_response, render_template, current_app as app, request, jsonify
from quart.datastructures import FileStorage
from quart_jwt_extended import get_jwt_identity, jwt_required

from shared.classful import route, QuartClassful
from http import HTTPStatus
import os
from datetime import datetime
from aiocache import cached
from typing import Literal

import io
from importlib import util
from PIL import Image
import requests
from contextlib import asynccontextmanager

from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
import msgpack


class RMQBroker(RabbitBroker):

    def __init__(self, app, *args, **kwargs):
        self.RABBITMQ_MEDIA_QUEUE = RabbitQueue(os.environ["RABBITMQ_MEDIA_QUEUE"])
        self.RABBITMQ_R18E_QUEUE = RabbitQueue(os.environ["RABBITMQ_R18E_QUEUE"])

        self.logger = app.logger

        if app.microservice_instance.needs_rmq():
            super().__init__(
                url=os.environ["RABBITMQ_URI"],
                decoder=self.decode_message,
                *args,
                **kwargs
            )

        if app.microservice_instance == "MEDIA":
            from obstore.auth.google import GoogleCredentialProvider
            from obstore import store

            # self.OBS_STORE = GCSStore(os.environ["GCS_BUCKET_NAME"])
            credential_provider = GoogleCredentialProvider()
            self.logger.warning(
                "USING OBS WITH GCS_BUCKET_URI: %s ", os.environ["GCS_BUCKET_URI"]
            )
            self.OBS_STORE = store.from_url(
                os.environ["GCS_BUCKET_URI"], credential_provider=credential_provider
            )

            @self.subscriber(self.RABBITMQ_MEDIA_QUEUE)
            async def handle_media_upload(message):
                await self.upload_to_bucket(message.headers, message.body)
                name = message.headers.get("filename", "")

                if "event" in name:
                    await self._publish_r18e(name, message.body, "MEDIA")
                elif "post" in name:
                    await self._publish_r18e(name, message.body, "POST")
                else:
                    self.logger.warning("Unknown filename: %s", name)

                await message.ack()

    async def decode_message(self, msg: RabbitMessage, original_decoder):
        try:
            msg.body = msgpack.loads(msg.body)
            return msg
        except:
            try:
                return await original_decoder(msg)
            except:
                return None

    async def upload_to_bucket(self, data, image_bytes: bytes):
        import obstore as obs

        await obs.put_async(
            self.OBS_STORE,
            data["filename"],
            io.BytesIO(image_bytes),
            attributes={"Content-Type": data["content-type"]},
        )

    async def _publish_r18e(
        self, filename, file, type: Literal["MEDIA", "POST", "EVENT"]
    ):

        file: bytes = (
            msgpack.dumps(file.read())
            if not isinstance(file, bytes)
            else msgpack.dumps(file)
        )
        await self.publisher(self.RABBITMQ_R18E_QUEUE).publish(
            file,
            headers={"type": type, "filename": filename},
        )

    async def _publish_media(self, data: dict, file: io.BytesIO):
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
        file: bytes = msgpack.dumps(file.read())
        await self.publisher(self.RABBITMQ_MEDIA_QUEUE).publish(
            file,
            headers={
                "filename": data.get("filename"),
                "content-type": data.get("type"),
            },
        )
