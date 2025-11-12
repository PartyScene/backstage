from shared.microservice import client

from livestream.src.connectors import init_db
from livestream.src.views.base import BaseView
from livestream.src.tasks import StreamMonitor

# Create app instance
app = client.MicroService("LIVESTREAM", init_db, BaseView)

# Initialize stream monitor
stream_monitor = StreamMonitor(app)


@app.before_serving
async def start_stream_monitor():
    """Start the stream monitor background task."""
    await stream_monitor.start()


@app.after_serving
async def stop_stream_monitor():
    """Stop the stream monitor background task."""
    await stream_monitor.stop()
