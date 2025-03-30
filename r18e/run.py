from shared.microservice import client

from r18e.src.internals.connector import init_db
from r18e.src.routers.features import BaseView

# Create app instance
app = client.MicroService("R18E", init_db, BaseView)
