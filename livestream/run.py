from shared.microservice import client

from livestream.src.connectors import init_db
from livestream.src.views.base import BaseView
from livestream.src.tasks import StreamMonitor

# Create app instance
app = client.MicroService("LIVESTREAM", init_db, BaseView)

# Attach stream monitor to app instance (will be started by MicroService before_serving hook)
app.stream_monitor = StreamMonitor(app)
