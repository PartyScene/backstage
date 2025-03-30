from shared.microservice import client

from posts.src.connectors import init_db
from posts.src.views.base import BaseView

# Create app instance
app = client.MicroService("POSTS", init_db, BaseView)
