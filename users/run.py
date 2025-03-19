import asyncio
import pprint
from hypercorn.config import Config
from hypercorn.asyncio import serve
from shared.microservice import client

from users.src.connectors import init_db
from users.src.views.base import BaseView

# Create app instance
app = client.MicroService("USERS", init_db, BaseView)
