"""
Background task to monitor and terminate streams that exceed the 3-minute time limit.
"""
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quart import Quart

logger = logging.getLogger(__name__)


class StreamMonitor:
    """Monitor and enforce 3-minute time limit on live streams."""
    
    MAX_LIVE_SECONDS = 180  # 3 minutes
    CHECK_INTERVAL = 30  # Check every 30 seconds
    
    def __init__(self, app: 'Quart'):
        """
        Initialize the stream monitor.
        
        Args:
            app: Quart application instance
        """
        self.app = app
        self.running = False
        self._task = None
    
    async def start(self):
        """Start the background monitoring task."""
        if self.running:
            logger.warning("Stream monitor already running")
            return
        
        self.running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Stream monitor started (checking every {self.CHECK_INTERVAL}s for streams >{self.MAX_LIVE_SECONDS}s)")
    
    async def stop(self):
        """Stop the background monitoring task."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Stream monitor stopped")
    
    async def _monitor_loop(self):
        """Main monitoring loop that checks for expired streams periodically."""
        while self.running:
            try:
                await self._check_and_terminate_expired_streams()
            except Exception as e:
                logger.error(f"Error in stream monitor loop: {e}", exc_info=True)
            
            # Wait before next check
            await asyncio.sleep(self.CHECK_INTERVAL)
    
    async def _check_and_terminate_expired_streams(self):
        """Check for expired streams and terminate them."""
        try:
            # Import here to avoid circular imports
            from shared.workers import cloudflare_stream
            
            # Fetch all expired scenes
            expired_scenes = await self.app.conn.fetch_expired_scenes(self.MAX_LIVE_SECONDS)
            
            if not expired_scenes:
                logger.debug("No expired streams found")
                return
            
            # Normalize to list
            scenes_list = expired_scenes if isinstance(expired_scenes, list) else [expired_scenes]
            
            logger.warning(f"Found {len(scenes_list)} expired stream(s) to terminate")
            
            # Initialize Cloudflare client if needed
            scenes_client = cloudflare_stream.create_livestream_client(self.app, logger)
            if not scenes_client._initialized:
                await scenes_client.initialize()
            
            # Terminate each expired stream
            for scene in scenes_list:
                try:
                    scene_id = scene.get("id", "").split(":")[-1] if ":" in scene.get("id", "") else scene.get("id", "")
                    input_uid = scene.get("input_uid")
                    user_info = scene.get("user_info", {})
                    user_id = user_info.get("id", "").split(":")[-1] if isinstance(user_info.get("id"), str) and ":" in user_info.get("id", "") else user_info.get("id", "unknown")
                    
                    logger.warning(
                        f"Terminating expired stream - scene_id: {scene_id}, "
                        f"user: {user_id}, input_uid: {input_uid}"
                    )
                    
                    # Delete from Cloudflare
                    if input_uid:
                        try:
                            await scenes_client._delete_input(input_uid)
                            logger.info(f"Deleted Cloudflare input {input_uid}")
                        except Exception as cf_err:
                            logger.error(f"Failed to delete Cloudflare input {input_uid}: {cf_err}")
                    
                    # Delete from database
                    deleted = await self.app.conn.delete_scene_by_id(scene_id)
                    if deleted:
                        logger.info(f"Deleted scene {scene_id} from database")
                        
                        # Invalidate cache if event_id is available
                        event_id = scene.get("event")
                        if event_id:
                            # Extract event ID from RecordID format
                            if isinstance(event_id, dict) and "id" in event_id:
                                event_id = event_id["id"]
                            if isinstance(event_id, str) and ":" in event_id:
                                event_id = event_id.split(":")[-1]
                            
                            try:
                                await self.app.redis.delete(f"livestream:all:{event_id}")
                                logger.info(f"Invalidated cache for event {event_id}")
                            except Exception as cache_err:
                                logger.error(f"Failed to invalidate cache: {cache_err}")
                    else:
                        logger.warning(f"Scene {scene_id} not found in database (may have been already deleted)")
                    
                except Exception as scene_err:
                    logger.error(f"Failed to terminate scene {scene.get('id')}: {scene_err}", exc_info=True)
            
            logger.info(f"Stream expiration check completed - terminated {len(scenes_list)} stream(s)")
            
        except Exception as e:
            logger.error(f"Error checking expired streams: {e}", exc_info=True)
