from shared.microservice import client

from livestream.src.connectors import init_db
from livestream.src.views.base import BaseView
from livestream.src.tasks import StreamMonitor

# Create app instance
app = client.MicroService("LIVESTREAM", init_db, BaseView)

# Attach stream monitor to app instance (will be started by MicroService before_serving hook)
app.stream_monitor = StreamMonitor(app)

# Verify assignment happened
import logging
logger = logging.getLogger(__name__)
logger.warning(f"run.py: stream_monitor assigned to app instance. hasattr check: {hasattr(app, 'stream_monitor')}")
