import asyncio
import uvloop
from hypercorn.config import Config
from hypercorn.asyncio import serve

from users.src import UsersMicroService

# Create app instance
app = UsersMicroService(__name__)

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
    uvloop.install()
    asyncio.run(serve(app, config))

if __name__ == "__main__":
    main()
