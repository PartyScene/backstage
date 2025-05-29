from shared.microservice import client

from payments.src.connectors import init_db
from payments.src.views.base import BaseView

# Create app instance
app = client.MicroService("PAYMENTS", init_db, BaseView)