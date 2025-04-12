import os
from typing import Literal, Annotated
from importlib import util
import io
from PIL import Image
import requests
from contextlib import asynccontextmanager

from faststream import FastStream, Context
from faststream.rabbit import RabbitBroker, RabbitMessage, RabbitQueue
import msgpack
from surrealdb import AsyncSurreal


import torch
from transformers import ViTImageProcessor, ViTModel

from aio_pika import IncomingMessage
import asyncio


class Job(RabbitBroker):

    def __init__(self, *args, **kwargs):
        self.RABBITMQ_R18E_QUEUE = RabbitQueue("R18E")

        self.processor = ViTImageProcessor.from_pretrained(
            "google/vit-base-patch16-224-in21k"
        )
        self.model = ViTModel.from_pretrained(
            "google/vit-base-patch16-224-in21k", output_hidden_states=True
        )
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.model = self.model.to(self.device)
        self._lock = asyncio.Lock()

        ##
        self.conn = AsyncSurreal(os.environ["SURREAL_URI"])

        super().__init__(
            url=os.environ["RABBITMQ_URI"], decoder=self.decode_message, *args, **kwargs
        )

        HeadersAnnotation = Annotated[dict, Context("message.headers")]

        @self.subscriber(self.RABBITMQ_R18E_QUEUE)
        async def handle_r18e(body, headers: HeadersAnnotation):
            await self.process_r18e_event(headers, body)
            # await msg.ack()

    async def save(self, filename, embeddings):
        async with self._lock:
            await self.conn.signin(
                {
                    "username": os.environ["SURREAL_USER"],
                    "password": os.environ["SURREAL_PASS"],
                }
            )
            await self.conn.use("partyscene", "partyscene")

            await self.conn.query(
                "UPDATE media SET embeddings = $embeddings WHERE filename = $filename",
                {"filename": filename, "embeddings": embeddings},
            )

    async def decode_message(self, msg: RabbitMessage, original_decoder):
        # self.logger.warning(msg)
        try:
            msg.body = msgpack.loads(msg.body)
            return msg
        except:
            return await original_decoder(msg)

    async def process_r18e_event(self, data: dict, body: bytes):
        option = data.get("type", None)
        match option:
            case "MEDIA":
                embeddings = await self.extract_media_embeddings(body)
                resp = await self.save(data.get("filename"), embeddings)
                return resp
            case "POST":
                embedding = ...
            case "EVENT":
                embedding = ...

    async def extract_media_embeddings(self, media_bytes: bytes):
        if util.find_spec("torch"):
            import torch

            image = Image.open(io.BytesIO(media_bytes)).convert("RGB")
            inputs = self.processor(images=image, return_tensors="pt").to(self.device)

            with torch.no_grad():
                outputs = self.model(**inputs)

                # Retrieve all hidden states
                hidden_states = (
                    outputs.hidden_states
                )  # Tuple of (num_layers+1, batch, seq_len, hidden_dim)

                # Get the last 4 hidden states
                last_4_layers = hidden_states[-4:]  # Last 4 layers

                # Option 1: Average over last 4 layers
                embedding = torch.stack(last_4_layers).mean(
                    dim=0
                )  # (batch, seq_len, hidden_dim)

            return embedding.tolist()


app = FastStream(Job())
