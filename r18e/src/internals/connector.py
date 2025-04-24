import os
import orjson as json

from quart import Quart
from surrealdb import AsyncSurreal, RecordID
from shared.utils import record_id_to_json
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager

from typing import Tuple


class R18E:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def recommend_similar_events(self, event_id: str) -> list[str]:
        """Recommend similar events based on embeddings."""

        # The flow will include us specifying an event to lookup, and then
        # Search for similar media relations and similar descriptions to the event
        # For the media, we get the mean media embedding
        # To get the mean media embeddings, let's get all media related to an event
        # LET $media_embeddings = (SELECT VALUE embeddings from media WHERE event = $event);

        # Then we can get the mean of the embeddings
        # Find the summ
        # LET $sum = $emb.reduce(|$a, $b| vector::add($a, $b));

        # Get the mean
        # LET $average_media_embedding = vector::scale($sum, <float> 1 / $emb.len() );
        # Then we can get the mean of the embeddings

        # next up we search for similar media
        # SELECT *, vector::distance::knn() as distance FROM media WHERE embeddings <|20, 40|> $average_media_embeddings

        # For the text, we only have one embedding.
        # LET $text_emb = (SELECT VALUE embeddings.text FROM $event);
        # SELECT vector::distance::knn() + vector::similarity::cosine(event.embeddings.text, $text_emb) as distance FROM media WHERE embeddings <|20, 40|> $average_media_embeddings

        #

        async with self.pool.acquire() as conn:
            await conn.let("event", RecordID("events", event_id))

            result = await conn.query_raw(
                """
                            -- LET $media_embeddings = (SELECT VALUE embeddings from media WHERE event = $event);
                            LET $media_embeddings = SELECT VALUE (->has_media->media.embeddings) FROM $event;
                            
                            LET $sum = $media_embeddings.reduce(
                                |$a, $b| vector::add($a, $b)
                                );
                                
                            LET $average_media_embeddings = vector::scale(
                                $sum, <float> 1 / $emb.len() 
                                );
                            
                            LET $text_emb = (SELECT VALUE embeddings.text FROM $event);
                            
                            SELECT event.*, vector::distance::knn() + vector::similarity::cosine(event.embeddings.text, $text_emb[0]) AS distance 
                            OMIT event.embeddings 
                            FROM media WHERE embeddings <|20, 40|> $average_media_embeddings 
                            ORDER BY distance;
                            
                             """
            )
            data = result['result'][-1]
            if data['status'] == 'ERR':
                raise Exception(f"Error fetching recommendations: {data['result']}")
            
            recommendations = data['result']
            return record_id_to_json(recommendations)

    async def fetch_embedding(self, event_id: str) -> dict:
        """Fetch an embedding for an event."""
        self.logger.warning(f"Fetching embedding for event {event_id}")
        return await self.pool.execute_query(
            f"SELECT * FROM embeddings WHERE id = $id", {"id": event_id}
        )


async def init_db(app: Quart) -> Tuple[R18E, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an instance.

    Args:
        app: The Quart application instance

    Returns:
        Initialized database connector
    """
    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()

    # Create a connection pool for events service
    pool = await pool_manager.create_pool(
        name="r18e_pool",
        uri=SURREAL_URI,
        credentials={"username": SURREAL_USER, "password": SURREAL_PASS},
        namespace=NAMESPACE,
        database=DATABASE,
        min_connections=2,
        max_connections=10,
        max_idle_time=300,
        connection_timeout=5.0,
        acquisition_timeout=10.0,
        health_check_interval=30,
        max_usage_count=1000,
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    return R18E(pool, app.logger), pool_manager
