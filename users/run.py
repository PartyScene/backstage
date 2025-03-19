from shared.microservice import client

from users.src.connectors import init_db
from users.src.views.base import BaseView

# Create app instance
app = client.MicroService("USERS", init_db, BaseView)
