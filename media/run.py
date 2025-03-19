import asyncio
import pprint
from hypercorn.config import Config
from hypercorn.asyncio import serve
from shared.microservice import client

from media.src.connectors import init_db
from media.src.views.base import BaseView

# Create app instance
app = client.MicroService("MEDIA", init_db, BaseView)
