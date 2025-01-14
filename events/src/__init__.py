import json
from pprint import pprint

from quart_redis import RedisHandler
from quart_schema import QuartSchema
import logging

from quart import Quart, request, websocket
from quart_jwt_extended import JWTManager, jwt_required, get_jwt_identity

from .connectors import EventsDB, init_db
from .views.base import BaseView


class EventsMicroService(Quart):

    def __init__(self, *args):
        super(EventsMicroService, self).__init__(*args)
        QuartSchema(self)

        logging.basicConfig(
            level=logging.INFO , format="%(asctime)s %(levelname)s %(message)s"
        )

        self.db: EventsDB = None  # Asyncpg pool
        self.logging = logging
        self.config.from_pyfile("/app/shared/settings.py")

        self.redis_handler = RedisHandler(self)

        @self.before_request
        async def log_request():
            self.logging.info(f"Request received: {request.method} {request.path}")
            self.logging.debug(f"Request body: {await request.get_json()}")
            self.logging.debug(f"KEYS: {self.config['SECRET_KEY']}")

        @self.before_serving
        async def before_serv():
            await self.services()

    async def services(self):
        """Initialize services before app is being served."""
        logging.info("Initializing SurrealDB Database Connection...")
        self.db = await init_db(self)
        
        logging.info("Registering Application Routes.")
        BaseView.register(self)

        # Register WebSocket route
        @self.websocket("/events/<event_id>/live/ws")
        @jwt_required
        async def event_live_updates(event_id: str):
            try:
                user_id = await get_jwt_identity()
                
                # Verify user has access to this event
                event = await self.db.fetch(event_id)
                self.logger.info(event)
                if not event or (
                    event['host']['id'] != user_id and 
                    user_id not in [a['id'] for a in event.get('attendees', [])]
                ):
                    return  # WebSocket will not be accepted

                # Get live query ID from Redis
                live_id = await self.redis_handler.get_connection().get(f"live_query:{event_id}")
                if not live_id:
                    return  # WebSocket will not be accepted

                await websocket.accept()
                
                try:
                    # Get notifications generator
                    notifications = await self.db.get_live_notifications(live_id)
                    
                    # Process notifications
                    async for notification in notifications:
                        if notification:
                            await websocket.send(json.dumps(notification))
                            
                except Exception as e:
                    self.logging.error(f"WebSocket error: {str(e)}")
                finally:
                    # Cleanup
                    try:
                        await self.db.kill_live_query(live_id)
                        await self.redis_handler.get_connection().delete(f"live_query:{event_id}")
                    except Exception as e:
                        self.logging.error(f"Cleanup error: {str(e)}")
                        
            except Exception as e:
                self.logging.error(f"Live updates error: {str(e)}")

        logging.info("Printing Application Routes...")
        logging.info(self.url_map)

        logging.info("Retrieving Secret...")
        await self.get_shared_secret()

    async def get_shared_secret(self):
        """"""
        conn = self.redis_handler.get_connection()
        self.config["SECRET_KEY"] = await conn.get("SECRET_KEY")

        # Then Initialize JWT
        self.jwt = JWTManager(self)

    def run(self):
        """Custom Run Method."""
        super(EventsMicroService, self).run(
            host="0.0.0.0", 
            port=5510
        )




