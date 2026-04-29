from quart import Quart
from surrealdb import AsyncSurreal, RecordID
import os
from typing import Optional, Tuple, Any, List, Dict
from shared.utils import record_id_to_json, report_resource
from purreal import SurrealDBConnectionPool, SurrealDBPoolManager


import orjson as json


PROFILE_SLUG_MIN_LEN = 3
PROFILE_SLUG_MAX_LEN = 50
HOST_GALLERY_MAX_ITEMS = 20


class SlugConflictError(Exception):
    """Raised when a profile_slug normalization collides with another user.

    Kept as its own exception so views can map it cleanly to HTTP 409 without
    string-matching ValueError messages.
    """


class UsersDB:
    def __init__(self, pool: SurrealDBConnectionPool, logger) -> None:
        self.pool = pool
        self.logger = logger

    async def _report_resource(self, data: dict):
        """
        Report this resource which is a user
        Args:
            data (dict): The data to report
        """
        return await report_resource(self.pool, data, resource_table="users")

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def get_connections_at_degree(self, origin_id: str, max_degree: int = 3):
        """
        Find all connections up to N degrees of separation

        Args:
            origin_id (str): The ID of the origin user
            max_degree (int): Maximum degree of separation (default: 3)

        Returns:
            dict: Contains connections at different degrees
        """
        if max_degree < 1 or max_degree > 6:
            return {"error": "Degree must be between 1 and 6"}

        async with self.pool.acquire() as conn:

            result = await conn.query(
                "RETURN fn::get_friends($origin);",
                {"origin": RecordID("users", origin_id)},
            )
        return record_id_to_json(result)
    
    async def fetch_user_tickets(self, user_id: Any, page: int = 1, limit: int = 50):
        """
        Fetch tickets bought by this user

        Args:
            user_id (str, required): The origin user ID
            page (int, optional): The page number (default: 1)
            limit (int, optional): The number of tickets per page (default: 50)
        Returns:
            list: The created relationship details
        """

        async with self.pool.acquire() as conn:

            result = await conn.query(
                "RETURN fn::fetch_user_tickets($origin, $page, $limit);",
                {
                    "origin": RecordID("users", user_id),
                    "page": page,
                    "limit": limit,
                },
            )
        return record_id_to_json(result)

    async def fetch_user_events(self, user_id: Any, created: bool = False):
        """
        Fetch events attended by this user

        Args:
            user_id (str, required): The origin user ID
        Returns:
            list: The created relationship details
        """
        if created:
            # Execute both queries concurrently with separate connections to avoid timeout
            import asyncio
            
            async def fetch_attended():
                async with self.pool.acquire() as conn:
                    return await conn.query(
                        "RETURN fn::fetch_attended_events($origin);",
                        {"origin": RecordID("users", user_id)},
                    )
            
            async def fetch_created():
                async with self.pool.acquire() as conn:
                    return await conn.query(
                        "RETURN fn::fetch_created_events($origin);",
                        {"origin": RecordID("users", user_id)},
                    )
            
            # Execute both queries in parallel
            attended_result, created_result = await asyncio.gather(
                fetch_attended(), fetch_created()
            )
            result = {"attended": attended_result, "created": created_result}
        else:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    "RETURN fn::fetch_attended_events($origin);",
                    {"origin": RecordID("users", user_id)},
                )

        return record_id_to_json(result)

    async def create_friend_relationship(self, data: dict):
        """
        Create a bidirectional friend relationship between two users.

        Args:
            data (dict, required): The friend relationship data containing:
                - origin: The ID of the first user
                - target: The ID of the second user
                - status: Optional relationship status ('pending', 'accepted', 'blocked')
        Returns:
            dict: The created relationship details
        """
        # First check if relationship already exists
        async with self.pool.acquire() as conn:

            result = await conn.query(
                "RETURN fn::create_relationship($origin, $target, $status);",
                {
                    "origin": RecordID("users", data["origin_id"]),
                    "target": RecordID("users", data["target_id"]),
                    "status": data.get("status", "pending"),
                },
            )

        return record_id_to_json(result["relationship"])

    async def update_friend_relationship(self, connection_id: str, data: dict):
        """
        Update the connection status between two users

        Args:
            connection_id (str, required): The ID of the connection
            data (dict, required): The friend relationship data containing:
                - origin: The ID of the first user
                - target: The ID of the second user
                - status: Optional relationship status ('pending', 'accepted', 'blocked', 'removed', 'rejected')
        Returns:
            dict: The updated relationship details
        """
        async with self.pool.acquire() as conn:
            await conn.let("edge", RecordID("friends", connection_id))
            query = """
                    UPDATE ONLY $edge SET status = $status
                """
            result = await conn.query(query, {"status": data.get("status", "pending")})
        return record_id_to_json(result)

    async def delete_connection(self, connection_id: str):
        """
        Delete the connection between two users

        Args:
            connection_id (str, required): The ID of the connection
        Returns:
            dict: The deleted relationship details
        """
        async with self.pool.acquire() as conn:
            await conn.let("edge", RecordID("friends", connection_id))
            query = """
                DELETE ONLY $edge
            """
            result = await conn.query(query)
        return record_id_to_json(result)

    async def block_user(self, blocker_id: str, blocked_id: str):
        """
        Create a block relationship between two users (unidirectional).
        blocker_id blocks blocked_id.

        Args:
            blocker_id (str): The ID of the user who is blocking
            blocked_id (str): The ID of the user being blocked

        Returns:
            dict: The created block relationship
        """
        async with self.pool.acquire() as conn:
            # Check if block relationship already exists
            existing = await conn.query(
                """
                SELECT * FROM blocks WHERE in = $blocker 
                AND out = $blocked
                """,
                {"blocker": RecordID("users", blocker_id), "blocked": RecordID("users", blocked_id)}
            )
            
            if existing:
                return record_id_to_json(existing[0])
            
            # Create block relationship
            result = await conn.query(
                """
                RELATE ONLY $blocker -> blocks -> $blocked
                SET created_at = time::now()
                """,
                {"blocker": RecordID("users", blocker_id), "blocked": RecordID("users", blocked_id)}
            )
            
        return record_id_to_json(result)

    async def unblock_user(self, blocker_id: str, blocked_id: str):
        """
        Remove a block relationship between two users.

        Args:
            blocker_id (str): The ID of the user who is unblocking
            blocked_id (str): The ID of the user being unblocked

        Returns:
            dict: The deleted block relationship or None if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                DELETE blocks WHERE in = $blocker 
                AND out = $blocked
                RETURN BEFORE
                """,
                {"blocker": RecordID("users", blocker_id), "blocked": RecordID("users", blocked_id)}
            )
            
        return record_id_to_json(result) if result else None

    async def get_blocked_users(self, user_id: str):
        """
        Fetch all users blocked by a specific user.

        Args:
            user_id (str): The ID of the user who is blocking.

        Returns:
            list: A list of blocked user objects.
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT ->blocks->users as blocked FROM $user
                """,
                {"user": RecordID("users", user_id)}
            )
            if result and len(result) > 0 and 'blocked' in result[0] and result[0]['blocked']:
                return record_id_to_json(result[0]['blocked'])
        return []

    async def fetch(self, id: str) -> Optional[dict]:
        """
        Fetch one user by ID

        Args:
            id (str): The user ID to fetch

        Returns:
            Optional[dict]: User data including attended events, or None if not found
        """  # ->attends->events[WHERE true] AS scenes,
        # ->friends
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                SELECT
                    * OMIT password
                FROM ONLY type::thing('users', $id);
            """,
                {"id": id},
            )
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def delete(self, id: str) -> Optional[dict]:
        """
        Delete a user by ID

        Args:
            id (str): The user ID to delete

        Returns:
            Optional[dict]: Deleted user data or None if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.delete(RecordID("users", id))
        return result

    def subset(self, d, keys):
        return {k: d[k] for k in keys if k in d}
    
    async def recommend_friends(self, user_id: str, limit: int = 20) -> list:
        """
        Return ranked friend recommendations by combining three signals:
          - Visual similarity  (40%) — HNSW KNN on ViT-768 media embeddings
          - Co-attendance      (35%) — shared event history via attends relation
          - Mutual friends     (25%) — degree-2 social graph

        Automatically excludes existing connections, blocked users, and self.

        Args:
            user_id (str): The requesting user's raw ID (without 'users:' prefix)
            limit   (int): Max recommendations to return (default 20)

        Returns:
            list: [
                {
                    "user": { id, first_name, last_name, username, avatar, organization_name },
                    "score": float,          # 0–1, descending
                    "signals": {
                        "shared_events":     int,
                        "visual_similarity": float,
                        "mutual_friends":    int
                    }
                },
                ...
            ]
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "RETURN fn::recommend_friends($user, $limit);",
                {
                    "user":  RecordID("users", user_id),
                    "limit": limit,
                },
            )
        return record_id_to_json(result)


    async def update(self, data: dict) -> dict:
        """
        Update user data

        Args:
            data (dict): User data to update, must include 'id' field

        Returns:
            dict: Updated user data
        """

        if "filename" in data:
            async with self.pool.acquire() as conn:
                data["creator"] = RecordID("users", data["id"])
                media_query_result = await conn.create(
                    "media", self.subset(data, ["filename", "type", "creator"])
                )
                self.logger.warning(
                    json.dumps(
                        media_query_result, option=json.OPT_INDENT_2, default=str
                    )
                )

                # if isinstance(media_query_result, dict):
                #     data["avatar"] = media_query_result["id"]
        
        data.pop("type", None)
        
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "UPDATE ONLY type::thing('users', $record_id) MERGE $content RETURN AFTER;",
                {"content": data, "record_id": data["id"]},
            )
        self.logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)


    # ------------------------------------------------------------------
    # Host profile: slug + flexible socials
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_slug_input(raw: Any) -> bool:
        """Sanity-check raw slug input before sending it to SurrealDB.

        Server-side normalization with `string::slug` is the source of truth
        for what's "valid" — this just rejects shapes that obviously can't
        produce a sensible slug (non-strings, empty, absurdly long).
        """
        return (
            isinstance(raw, str)
            and PROFILE_SLUG_MIN_LEN <= len(raw.strip()) <= 200
        )

    async def fetch_by_slug(self, slug: str) -> Optional[dict]:
        """Resolve a profile_slug to a user record (or None)."""
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "SELECT * OMIT password, hashed_password, hashed_email "
                "FROM users WHERE profile_slug = $slug LIMIT 1;",
                {"slug": slug},
            )
        if not result:
            return None
        first = result[0] if isinstance(result, list) else result
        return record_id_to_json(first) if first else None

    async def set_profile_slug(self, user_id: str, raw: str) -> str:
        """
        Normalize and assign a profile_slug atomically.

        Pipeline (single `query_raw` round-trip):
            1. `string::slug($raw)` — SurrealDB's built-in normalizer turns
               "DJ Mike!" into "dj-mike", so the client doesn't have to know
               our slug rules. Returns "" for unrenderable input.
            2. Length / non-empty check.
            3. Uniqueness check (excluding the current user).
            4. UPDATE user SET profile_slug.

        Raises:
            ValueError    — input fails length/empty checks
            SlugConflictError — slug is taken by another user

        Returns the final normalized slug string on success.
        """
        if not self.is_valid_slug_input(raw):
            raise ValueError(
                f"profile_slug must be a {PROFILE_SLUG_MIN_LEN}-200 char string."
            )

        async with self.pool.acquire() as conn:
            await conn.let("u", RecordID("users", user_id))
            await conn.let("raw", raw)

            response = await conn.query_raw(
                f"""
                LET $slug = string::slug($raw);
                LET $valid = string::len($slug) >= {PROFILE_SLUG_MIN_LEN}
                              AND string::len($slug) <= {PROFILE_SLUG_MAX_LEN};
                LET $taken = SELECT id FROM users
                             WHERE profile_slug = $slug AND id != $u
                             LIMIT 1;

                RETURN {{
                    slug:  $slug,
                    valid: $valid,
                    taken: count($taken) > 0
                }};
                """
            )

        statements = response.get("result", []) if isinstance(response, dict) else []
        for stmt in statements:
            if isinstance(stmt, dict) and stmt.get("status") == "ERR":
                raise Exception(f"set_profile_slug failed: {stmt.get('result')}")

        final = statements[-1] if statements else {}
        info = final.get("result") if isinstance(final, dict) else {}
        if not isinstance(info, dict):
            raise Exception("set_profile_slug returned no payload.")

        slug = info.get("slug") or ""
        if not info.get("valid"):
            raise ValueError(
                "profile_slug is empty after normalization or out of range."
            )
        if info.get("taken"):
            raise SlugConflictError("profile_slug already taken.")

        # Separate UPDATE so the previous LETs stay focused on validation —
        # easier to read than wrapping the assignment inside the same block.
        async with self.pool.acquire() as conn:
            await conn.query(
                "UPDATE ONLY type::thing('users', $uid) "
                "SET profile_slug = $slug RETURN VALUE profile_slug;",
                {"uid": user_id, "slug": slug},
            )

        return slug

    async def fetch_host_profile(
        self, user_id: str, viewer_id: Optional[str] = None
    ) -> Optional[dict]:
        """
        Aggregate the public host profile in a single round-trip.

        Uses `query_raw` so we get the full multi-statement envelope and can
        pull only the final RETURN object — same pattern used for the
        recommendation engine in r18e/src/internals/connector.py.

        Variables are bound up-front via `conn.let(...)` so the SurrealQL
        block can refer to `$u` and `$v` without re-binding inside every
        statement.
        """
        async with self.pool.acquire() as conn:
            await conn.let("u", RecordID("users", user_id))
            await conn.let(
                "v",
                RecordID("users", viewer_id) if viewer_id else None,
            )

            response = await conn.query_raw(
                """
                LET $user = SELECT
                    * OMIT password, hashed_password, hashed_email,
                    cover_image.* AS cover_image
                FROM ONLY $u;

                LET $total_events    = (SELECT count() FROM events
                                        WHERE host = $u GROUP ALL)[0].count ?? 0;
                LET $total_attendees = (SELECT count() FROM tickets
                                        WHERE event.host = $u GROUP ALL)[0].count ?? 0;
                LET $follower_count  = (SELECT count() FROM host_followers
                                        WHERE out = $u GROUP ALL)[0].count ?? 0;
                LET $is_following    = $v != NONE
                    AND count(SELECT id FROM host_followers
                              WHERE in = $v AND out = $u) > 0;

                LET $upcoming = SELECT * FROM events
                    WHERE host = $u AND time > time::now()
                    ORDER BY time ASC LIMIT 10;
                LET $past = SELECT * FROM events
                    WHERE host = $u AND time <= time::now()
                    ORDER BY time DESC LIMIT 20;
                LET $media = SELECT *, out.* AS media FROM host_media
                    WHERE in = $u
                    ORDER BY sort_order ASC, created_at ASC;

                RETURN {
                    user:            $user,
                    total_events:    $total_events,
                    total_attendees: $total_attendees,
                    follower_count:  $follower_count,
                    is_following:    $is_following,
                    upcoming_events: $upcoming,
                    past_events:     $past,
                    media:           $media
                };
                """
            )

        # query_raw returns one entry per statement. The final RETURN is the
        # only one we care about, and a non-OK status anywhere in the chain
        # should surface so we don't ship a half-built profile.
        statements = response.get("result", []) if isinstance(response, dict) else []
        if not statements:
            return None
        for stmt in statements:
            if isinstance(stmt, dict) and stmt.get("status") == "ERR":
                raise Exception(f"fetch_host_profile failed: {stmt.get('result')}")

        final = statements[-1]
        payload = final.get("result") if isinstance(final, dict) else final
        if payload is None or (isinstance(payload, dict) and payload.get("user") is None):
            return None
        return record_id_to_json(payload)

    async def backfill_host_since(self, user_id: str) -> Optional[dict]:
        """Set host_since to the earliest hosted event time if missing."""
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                LET $u = type::thing('users', $user_id);
                LET $earliest = (SELECT VALUE time FROM events
                                  WHERE host = $u
                                  ORDER BY time ASC LIMIT 1)[0];
                IF $earliest != NONE {
                    UPDATE ONLY $u SET host_since = $earliest
                        WHERE host_since = NONE
                        RETURN AFTER;
                };
                """,
                {"user_id": user_id},
            )
        return record_id_to_json(result) if result else None

    # ------------------------------------------------------------------
    # Host follower graph
    # ------------------------------------------------------------------

    async def follow_host(self, follower_id: str, host_id: str) -> Optional[dict]:
        """
        Idempotently RELATE follower -> host_followers -> host.

        Returns the existing edge if already present so callers can treat
        repeat follows as a no-op without surfacing a constraint error.
        """
        if follower_id == host_id:
            raise ValueError("Cannot follow yourself.")

        async with self.pool.acquire() as conn:
            existing = await conn.query(
                """
                SELECT * FROM host_followers
                WHERE in = type::thing('users', $follower)
                  AND out = type::thing('users', $host)
                LIMIT 1;
                """,
                {"follower": follower_id, "host": host_id},
            )
            if existing:
                return record_id_to_json(existing[0])

            result = await conn.query(
                """
                RELATE ONLY type::thing('users', $follower)
                       -> host_followers ->
                       type::thing('users', $host)
                SET created_at = time::now();
                """,
                {"follower": follower_id, "host": host_id},
            )
        return record_id_to_json(result)

    async def unfollow_host(self, follower_id: str, host_id: str) -> Optional[dict]:
        """Delete the follow edge if it exists; return BEFORE record or None."""
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                DELETE host_followers
                WHERE in = type::thing('users', $follower)
                  AND out = type::thing('users', $host)
                RETURN BEFORE;
                """,
                {"follower": follower_id, "host": host_id},
            )
        if not result:
            return None
        first = result[0] if isinstance(result, list) and result else result
        return record_id_to_json(first) if first else None

    # ------------------------------------------------------------------
    # Cover image
    # ------------------------------------------------------------------

    async def set_cover_media(self, user_id: str, filename: str, content_type: str) -> dict:
        """
        Create a media record for a cover upload and merge it onto the user.

        Mirrors the existing avatar pattern in `update`: a media row is the
        canonical reference so the RMQ pipeline can attach metadata, blurhash,
        and signing later. We store the media RecordID on `cover_image`.
        """
        async with self.pool.acquire() as conn:
            media = await conn.create(
                "media",
                {
                    "filename": filename,
                    "type": content_type,
                    "creator": RecordID("users", user_id),
                },
            )
            if not isinstance(media, dict):
                raise Exception(f"Failed to create cover media record: {media}")

            user = await conn.query(
                "UPDATE ONLY type::thing('users', $uid) "
                "SET cover_image = $media RETURN AFTER;",
                {"uid": user_id, "media": media["id"]},
            )
        return {
            "media": record_id_to_json(media),
            "user":  record_id_to_json(user),
        }

    # ------------------------------------------------------------------
    # Host gallery
    # ------------------------------------------------------------------

    async def count_host_gallery(self, user_id: str) -> int:
        """Return current gallery item count for a host."""
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "SELECT count() FROM host_media "
                "WHERE in = type::thing('users', $uid) GROUP ALL;",
                {"uid": user_id},
            )
        if not result:
            return 0
        first = result[0] if isinstance(result, list) else result
        return int(first.get("count", 0)) if isinstance(first, dict) else 0

    async def add_gallery_media(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        caption: Optional[str] = None,
        event_id: Optional[str] = None,
    ) -> dict:
        """
        Create a media record for a gallery upload and RELATE it via host_media.

        Sort order is appended to the end of the current gallery so the client
        can drag-reorder later through `reorder_gallery`.
        """
        current = await self.count_host_gallery(user_id)
        if current >= HOST_GALLERY_MAX_ITEMS:
            raise ValueError(
                f"Gallery is full ({HOST_GALLERY_MAX_ITEMS} items max)."
            )

        async with self.pool.acquire() as conn:
            media = await conn.create(
                "media",
                {
                    "filename": filename,
                    "type": content_type,
                    "creator": RecordID("users", user_id),
                },
            )
            if not isinstance(media, dict):
                raise Exception(f"Failed to create gallery media: {media}")

            relate_args: Dict[str, Any] = {
                "user":      RecordID("users", user_id),
                "media":     media["id"],
                "caption":   caption,
                "sort_order": current,
                "event":     RecordID("events", event_id) if event_id else None,
            }
            edge = await conn.query(
                """
                RELATE ONLY $user -> host_media -> $media
                SET caption    = $caption,
                    sort_order = $sort_order,
                    event      = $event;
                """,
                relate_args,
            )
        return {
            "media": record_id_to_json(media),
            "edge":  record_id_to_json(edge),
        }

    async def remove_gallery_media(self, user_id: str, media_id: str) -> bool:
        """
        Delete the host_media edge for (user_id, media_id).

        Only the edge is removed by default; the underlying media row is left
        alone because it may be referenced elsewhere (cover, posts, events).
        """
        async with self.pool.acquire() as conn:
            result = await conn.query(
                """
                DELETE host_media
                WHERE in = type::thing('users', $uid)
                  AND out = type::thing('media', $mid)
                RETURN BEFORE;
                """,
                {"uid": user_id, "mid": media_id},
            )
        if not result:
            return False
        first = result[0] if isinstance(result, list) and result else result
        return bool(first)

    async def reorder_gallery(self, user_id: str, ordered_media_ids: List[str]) -> List[dict]:
        """
        Replace the sort_order for the host's gallery with the supplied order.

        Validates ownership: any media id not currently in the host's gallery
        causes the whole reorder to fail so partial state can't slip through.
        """
        async with self.pool.acquire() as conn:
            current = await conn.query(
                """
                SELECT out FROM host_media
                WHERE in = type::thing('users', $uid);
                """,
                {"uid": user_id},
            )
            owned = {
                str(row["out"]).split(":")[-1]
                for row in (current or [])
                if isinstance(row, dict) and row.get("out") is not None
            }
            requested = set(ordered_media_ids)
            if not requested.issubset(owned):
                raise ValueError("Reorder list contains media not in this host's gallery.")

            updates = []
            for index, media_id in enumerate(ordered_media_ids):
                updates.append(
                    await conn.query(
                        """
                        UPDATE host_media
                        SET sort_order = $sort
                        WHERE in = type::thing('users', $uid)
                          AND out = type::thing('media', $mid)
                        RETURN AFTER;
                        """,
                        {"uid": user_id, "mid": media_id, "sort": index},
                    )
                )
        return record_id_to_json(updates)


async def init_db(app) -> Tuple[UsersDB, SurrealDBConnectionPool]:
    """
    Initialize the database connection pool and return an UsersDB instance.

    Args:
        app: The Quart application instance

    Returns:
        Tuple[UsersDB, SurrealDBConnectionPool]: Initialized database connector and connection pool
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
        name="users_pool",
        uri=SURREAL_URI,
        credentials={"username": SURREAL_USER, "password": SURREAL_PASS},
        namespace=NAMESPACE,
        database=DATABASE,
        min_connections=3,
        max_connections=20,  # Increased from 10 to handle more concurrent requests
        max_idle_time=60,  # Reduced from 300s - recycle idle connections faster
        connection_timeout=10.0,  # Increased from 5s to allow slower connection establishment
        acquisition_timeout=30.0,  # Increased from 10s to 30s to prevent premature cancellation
        health_check_interval=10,  # Reduced from 30s - check health more frequently
        max_usage_count=100,  # Reduced from 1000 - recycle connections more aggressively
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        schema_file=SCHEMA_FILE,
        reset_on_return=True,
        log_queries=True,
    )

    # Create UsersDB instance
    users_db = UsersDB(pool, app.logger)

    return users_db, pool_manager
