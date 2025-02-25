import asyncio
import os
from hypercorn.config import Config
from hypercorn.asyncio import serve

from .src import EventsMicroService

# Create app instance
app = EventsMicroService(__name__)

# Configure Hypercorn
config = Config()
config.bind = ["0.0.0.0:5510"]
config.use_reloader = False
config.worker_class = "asyncio"
config.workers = 4
config.accesslog = "-"
config.errorlog = "-"
config.keepalive_timeout = 120

def main():
    """Run the application with uvloop"""
    if os.name == "nt":
        ...
    else:
        import uvloop
        uvloop.install()
    asyncio.run(serve(app, config))

if __name__ == "__main__":
    main()
