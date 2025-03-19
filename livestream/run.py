import asyncio
import pprint
from hypercorn.config import Config
from hypercorn.asyncio import serve
from shared.microservice import client

from livestream.src.connectors import init_db
from livestream.src.views.base import BaseView

# Create app instance
app = client.MicroService("LIVESTREAM", init_db, BaseView)
