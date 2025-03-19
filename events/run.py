import asyncio
import pprint
from hypercorn.config import Config
from hypercorn.asyncio import serve
from shared.microservice import client

from events.src.connectors import init_db
from events.src.views.base import BaseView

# Create app instance
app = client.MicroService("EVENTS", init_db, BaseView)
