from shared.microservice import client

from auth.src.connectors import init_db
from auth.src.views.base import BaseView

# Create app instance
# app = AuthMicroService(__name__)
app = client.MicroService("AUTH", init_db, BaseView)
