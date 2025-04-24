import os
from typing import Optional, Dict, Any

from surrealdb import AsyncSurreal
from shared.utils import record_id_to_json, AsyncEnvelopeCipherService
from purreal import SurrealDBPoolManager, SurrealDBConnectionPool

import orjson as json
import logging
import asyncio

# Get the logger
logger = logging.getLogger(__name__)


class AuthDB:
    """
    Authentication database connector that uses a connection pool
    to manage SurrealDB connections efficiently.
    """

    def __init__(self, pool: SurrealDBConnectionPool) -> None:
        """
        Initialize the AuthDB with a connection pool.

        Args:
            pool: The SurrealDB connection pool to use
        """
        self.pool = pool
        self.db = None  # For compatibility with existing code
        self.envelope_service = AsyncEnvelopeCipherService()

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")

    async def _create_lead(self, email: str, usecase: str) -> dict:
        """
        Create a new lead in the database.

        Args:
            email (str): Email address of the lead
            usecase (str): Use case of the lead

        Returns:
            dict: Created lead data or None if creation failed
        """
        # Generate Crypto credentials

        credentials = await self.envelope_service.encrypt(email.encode())
        credentials["usecase"] = usecase

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("leads", credentials)
                logger.debug(result)
                return record_id_to_json(result)
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            return None

    async def _login(self, data) -> dict:
        """
        Authenticate a user with email and password.

        Args:
            data: Dict containing email and password

        Returns:
            dict: User data if authentication succeeds, False otherwise
        """
        try:
            result = await self.pool.execute_query(
                "SELECT * FROM users WHERE crypto::argon2::compare(hashed_password, $password) AND crypto::argon2::compare(hashed_email, $email);",
                {"password": data["password"], "email": data["email"]},
            )
            logger.info(json.dumps(result, default=str, option=json.OPT_INDENT_2))

            if not result or not result[0]:
                logger.warning(
                    f"Wrong password or non-existent credentials for email {data.get('email')}"
                )
                return False

            return record_id_to_json(result[0])
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    async def _create_pending_user(self, form):
        """
        Create a new pending user in the database.

        Args:
            form: Form data to create the pending user

        Returns:
            dict: Created pending user data or None if creation failed
        """

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("pending_users", form)
                logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
                return record_id_to_json(result)
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None

    async def _verify_and_store(self, form):
        """
        Create a new user in the database after verifying the user's email.

        Args:
            form: User data to create

        Returns:
            dict: Created user data or None if creation failed
        """
        # Let's rewrite the form to fit the schema
        data = {
            "first_name": form.get("first_name", ""),
            "last_name": form.get("last_name", ""),
            "hashed_password": form.get("password", ""),
            "hashed_email": form.get("email", ""),
        }
        # Generate Crypto credentials
        credentials = await self.envelope_service.encrypt(form.get("email").encode())

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("users", {**form, **data})
                await conn.create("credentials", {**credentials, "user": result["id"]})

                logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
                return record_id_to_json(result)
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None

    async def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        """
        Execute a raw query against the database.

        Args:
            query: SurrealQL query string
            params: Optional query parameters

        Returns:
            Query results
        """
        return await self.pool.execute_query(query, params)


async def init_db(app) -> AuthDB:
    """
    Initialize the database connection pool and return an AuthDB instance.

    Args:
        app: The Quart application instance

    Returns:
        AuthDB: Initialized database connector
    """

    app.logger.info("Initializing SurrealDB connection...")

    SCHEMA_FILE = os.getenv("SCHEMA_FILE")
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"

    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()

    # Create a connection pool for auth service
    pool = await pool_manager.create_pool(
        name="auth_pool",
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

    # Create AuthDB instance
    auth_db = AuthDB(pool)

    # For backward compatibility with existing code
    # This allows code that directly accesses auth_db.db to still work
    async with pool.acquire() as conn:
        auth_db.db = conn

    return auth_db, pool_manager
