import os
from typing import Optional, Dict, Any
import logging
import typing
from datetime import datetime, UTC
from surrealdb import AsyncSurreal, RecordID
from shared.utils import record_id_to_json, AsyncEnvelopeCipherService
from purreal import SurrealDBPoolManager, SurrealDBConnectionPool
from redis import Redis
import orjson as json

# Get the logger
logger = logging.getLogger(__name__)


class AuthDB:
    """
    Authentication database connector that uses a connection pool
    to manage SurrealDB connections efficiently.
    """

    def __init__(self, pool: SurrealDBConnectionPool, redis: Redis) -> None:
        """
        Initialize the AuthDB with a connection pool.

        Args:
            pool: The SurrealDB connection pool to use
            redis: The Redis instance
        """
        self.pool = pool
        self.db = None  # For compatibility with existing code
        self.envelope_service = AsyncEnvelopeCipherService()
        self.redis = redis
        self.cuckoo_filter = self.redis.cf()

    async def _info(self):
        """Get database information."""
        return await self.pool.execute_query("INFO FOR DB")
    
    async def get_credentials(self, user_id:str):
        async with self.pool.acquire() as conn:
            result = await conn.query(
                "SELECT * OMIT user FROM credentials WHERE user = $user_id;",
                {"user_id": RecordID("users", user_id)},
            )
            return result
    
    async def decrypt_credentials(self, user_id:str):
        creds = await self.get_credentials(user_id)
        print(creds)
        return await self.envelope_service.decrypt(
            encrypted_data=creds[0]["encrypted_data"],
            encrypted_dek=creds[0]["encrypted_decryption_key"],
            data_initialization_vector=creds[0]["data_initialization_vector"],
            decryption_key_initialization_vector=creds[0]["decryption_key_initialization_vector"],
        )

    async def update_user(self, data: dict) -> dict:
        """
        Update user data

        Args:
            data (dict): User data to update, must include 'id' field

        Returns:
            dict: Updated user data
        """

        async with self.pool.acquire() as conn:
            result = await conn.query(
                "UPDATE ONLY type::thing('users', $record_id) MERGE $content RETURN AFTER;",
                {"content": data, "record_id": data["id"]},
            )
        logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        return record_id_to_json(result)

    async def _reset_password(self, email: str, new_password: str) -> Optional[bool]:
        """Reset the password for the user with the given email.

        Args:
            email (str): The email of the user whose password is to be reset.

        Returns:
            Optional[bool]: True if the password was reset successfully, False otherwise.
        """
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(
                    """UPDATE users SET hashed_password = crypto::argon2::generate($new_password) WHERE crypto::argon2::compare(hashed_email, $email);""",
                    {"email": email, "new_password": new_password},
                )

                # Expect a list with a single dict representing the updated record
                if not result or not isinstance(result[0], dict):
                    logger.warning(
                        "Password reset affected 0 rows for %s – result=%s",
                        email,
                        result,
                    )
                    return False

                return True

        except Exception as e:
            logger.exception(f"Error resetting password for {email}: {e}")
            return None

    async def _fetch_user_by_email(self, email: str) -> Optional[dict]:
        """
        Fetch user data from the database by email.

        Args:
            email (str): The email to fetch

        Returns:
            Optional[dict]: User data if found, or None if not found
        """
        return await self._fetch_user(email, "email")

    async def _fetch_user(
        self, param: str, type: typing.Literal["email", "username", "stripe_account_id"]
    ) -> Optional[dict]:
        """
        Fetch user data from the database by email or username.
        Args:
            param (str): The email or username to fetch
            type (typing.Literal["email", "username"]): The type of parameter ('email' or 'username')
        Returns:
            Optional[dict]: User data if found, or None if not found
        """
        match type:
            case "email":
                query = """
                SELECT * OMIT password FROM users WHERE crypto::argon2::compare(hashed_email, $param);
                """
            case "username":
                query = """
                SELECT * OMIT password FROM users WHERE username = $param;
                """
            case "stripe_account_id":
                query = """
                SELECT * OMIT password FROM users WHERE stripe_account_id = $param;
                """
            case _:
                raise ValueError("Invalid type specified. Use 'email', 'username' or 'stripe_account_id'.")
                
        # Execute the query to fetch user data
        try:
            async with self.pool.acquire() as conn:
                result = await conn.query(query, {"param": param})
            if not result:
                logger.warning(f"No user found for {type}: {param}")
                return None
        except Exception as e:
            logger.error(f"Error fetching user by {type}: {e}")
            return None

        logger.info(json.dumps(result, option=json.OPT_INDENT_2, default=str))
        # SurrealDB can return `[[]]` when no rows matched
        first = result[0] if result and result[0] else None
        return record_id_to_json(first) if first else None

    async def _create_lead(self, email: str, usecase: str) -> dict:
        """
        Create a new lead in the database.

        Args:
            email: Email address of the lead
            usecase: Use case of the lead

        Returns:
            dict: Created lead data or an empty dictionary if creation failed
        """
        # Generate Crypto credentials
        credentials = await self.envelope_service.encrypt(email.encode())
        credentials["usecase"] = usecase

        try:
            async with self.pool.acquire() as conn:
                result = await conn.create("leads", credentials)
                logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
                return record_id_to_json(result) if result else {}
        except Exception as e:
            logger.error(f"Error creating lead: {e}")
            return {}

    async def _check_exists(self, param, type) -> bool:
        """
        Check if a user with the given email or username exists in the database.
        Uses cuckoo filter for faster checks, falls back to database for misses.
        Includes error handling for filter inconsistencies.

        Args:
            param: The parameter value to check
            type: The type of parameter ('email' or 'username')

        Returns:
            bool: True if the user exists, False otherwise
        """
        try:
            # Try cuckoo filter first, but handle Redis errors gracefully
            try:
                in_cuckoo = await self.cuckoo_filter.exists(type, param)
                if bool(in_cuckoo):
                    return True
            except Exception as filter_error:
                logger.warning(f"Cuckoo filter error for {type}:{param} - {filter_error}. Falling back to database.")
                # Continue to database check if filter fails

            if type == "email":
                result = await self.pool.execute_query(
                    "SELECT * FROM users WHERE crypto::argon2::compare(hashed_email, $email);",
                    {"email": param},
                )
                logger.debug("Cuckoo miss, database result for email %s: %s" % (param, bool(result)))
                if bool(result):
                    try:
                        await self.cuckoo_filter.add("email", param)
                    except Exception as filter_error:
                        logger.warning(f"Failed to add email to cuckoo filter: {filter_error}")
                    return True

            elif type == "username":
                result = await self.pool.execute_query(
                    "SELECT * FROM users WHERE username = $username",
                    {"username": param},
                )
                logger.debug("Cuckoo miss, database result for username %s: %s" % (param, bool(result)))
                if bool(result):
                    try:
                        await self.cuckoo_filter.add("username", param)
                    except Exception as filter_error:
                        logger.warning(f"Failed to add username to cuckoo filter: {filter_error}")
                    return True

            return False
        except Exception as e:
            logger.error(f"Error checking if user exists: {e}")
            # On database errors, assume user exists to prevent duplicates
            return True

    async def _login(self, data) -> dict | None:
        """
        Authenticate a user with email and password.
        Blocks password login if user registered with SSO.

        Args:
            data: Dict containing email and password

        Returns:
            dict: User data if authentication succeeds
            None: If login fails
            str: If user must use SSO (returns "use_sso" or "use_google" or "use_apple")
        """
        try:
            email = data["email"]
            
            # First check if user exists with SSO auth provider
            sso_check = await self.pool.execute_query(
                "SELECT auth_provider, google_sub, apple_sub FROM users WHERE crypto::argon2::compare(hashed_email, $email);",
                {"email": email},
            )
            
            if sso_check and sso_check[0]:
                user = sso_check[0]
                auth_provider = user.get("auth_provider")
                
                # If user registered with SSO, block password login
                if auth_provider in ["google", "apple", "sso"]:
                    logger.info(f"User {email} registered with {auth_provider}, blocking password login")
                    
                    # Return specific SSO provider based on auth_provider field for better UX
                    if auth_provider == "google":
                        return "use_google"
                    elif auth_provider == "apple":
                        return "use_apple"
                    else:
                        return "use_sso"
            
            # Proceed with password authentication for password-registered users
            result = await self.pool.execute_query(
                "SELECT * FROM users WHERE auth_provider = 'password' AND hashed_password != NONE AND crypto::argon2::compare(hashed_password, $password) AND crypto::argon2::compare(hashed_email, $email);",
                {"password": data["password"], "email": email},
            )
            
            if not result:
                logger.warning(f"Wrong password or non-existent credentials for email {email}")
                return None

            return record_id_to_json(result[0])
            
        except Exception as e:
            logger.error(f"Login error: {e}")
            return None

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
                logger.debug(json.dumps(result, option=json.OPT_INDENT_2, default=str))
                return record_id_to_json(result)
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None

    async def sso_store(self, form):
        """
        Store or create a new user in the database for SSO Authentication.
        Handles race conditions and unique constraint violations robustly.

        Args:
            form: User data to create

        Returns:
            dict: Created user data or existing user data if already exists
        """
        email = form.get("email")
        if not email:
            logger.error("SSO store called without email")
            return None

        # Let's rewrite the form to fit the schema
        data = {
            "first_name": form.get("first_name", ""),
            "last_name": form.get("last_name", ""),
            "organization_name": form.get("organization_name", ""),
            "hashed_email": email,
            "email": email,
            "created_at": datetime.now(UTC),
            "auth_provider": form.get("auth_provider", "password" if form.get("password") else "sso"),
            "google_sub": form.get("google_sub", None),
            "apple_sub": form.get("apple_sub", None),
        }

        # Generate Crypto credentials
        credentials = await self.envelope_service.encrypt(email.encode())

        try:
            async with self.pool.acquire() as conn:
                # First attempt: Try to create the user
                try:
                    result = await conn.create("users", {**form, **data})
                    if isinstance(result, dict):
                        # Successfully created - update cuckoo filter
                        try:
                            await self.cuckoo_filter.add("email", email)
                        except Exception as filter_error:
                            logger.warning(f"Failed to add email to cuckoo filter: {filter_error}")

                        # Create credentials
                        await conn.create(
                            "credentials", {**credentials, "user": result["id"]}
                        )

                        logger.info(f"Created new SSO user: {email}")
                        return record_id_to_json(result)
                    else:
                        logger.warning(f"User creation returned unexpected result: {result}")

                except Exception as create_error:
                    # Check if this is a unique constraint violation
                    error_msg = str(create_error).lower()
                    if any(keyword in error_msg for keyword in ['unique', 'duplicate', 'already exists', 'constraint']):
                        logger.info(f"User already exists during SSO creation, checking for account linking: {email}")

                        # User already exists - check if we can link accounts
                        try:
                            existing_user = await self._fetch_user_by_email(email)
                            if existing_user:
                                # If existing user registered with password, link SSO account
                                if existing_user.get("auth_provider") == "password":
                                    logger.info(f"Linking SSO account to existing password user: {email}")
                                    
                                    # Update existing user with SSO fields
                                    update_data = {
                                        "id": existing_user["id"]
                                    }
                                    
                                    # Add SSO provider fields
                                    if form.get("google_sub"):
                                        update_data["google_sub"] = form.get("google_sub")
                                    if form.get("apple_sub"):
                                        update_data["apple_sub"] = form.get("apple_sub")
                                    
                                    # Update avatar if provided and user doesn't have one
                                    if form.get("avatar") and not existing_user.get("avatar"):
                                        update_data["avatar"] = form.get("avatar")
                                    
                                    # Update the user record with SSO linking
                                    linked_user = await self.update_user(update_data)
                                    if linked_user and isinstance(linked_user, dict):
                                        logger.info(f"Successfully linked SSO account for {email}")
                                        return linked_user
                                    else:
                                        logger.warning(f"Failed to link SSO account for {email}, returning existing user")
                                        return existing_user
                                else:
                                    # User already has SSO account
                                    logger.info(f"User {email} already has SSO account, returning existing")
                                    return existing_user
                            else:
                                logger.error(f"User should exist but fetch returned None: {email}")
                        except Exception as fetch_error:
                            logger.error(f"Error during account linking for {email}: {fetch_error}")
                    else:
                        logger.error(f"Unexpected error creating SSO user {email}: {create_error}")

                return None

        except Exception as e:
            logger.error(f"Critical error in sso_store for {email}: {e}")
            return None

    async def _store_after_verify(self, form):
        """
        Store or create a new user in the database after verifying the user's email.

        Args:
            form: User data to create

        Returns:
            dict: Created user data or None if creation failed
        """
        # Store email and username before popping them
        email = form.get("email", "")
        username = form.get("username", "")
        
        # Let's rewrite the form to fit the schema
        data = {
            "first_name": form.get("first_name", ""),
            "last_name": form.get("last_name", ""),
            "organization_name": form.get("organization_name", ""),
            "hashed_password": form.get("password", ""),
            "hashed_email": email,
        }
        # Generate Crypto credentials
        credentials = await self.envelope_service.encrypt(email.encode())

        try:
            async with self.pool.acquire() as conn:
                form.pop("password", None)
                form.pop("email", None)
                
                result = await conn.create("users", {**form, **data})
                if isinstance(result, dict):
                    # Use stored values instead of form.get after popping
                    try:
                        await self.cuckoo_filter.add("email", email)
                    except Exception as filter_error:
                        logger.warning(f"Failed to add email to cuckoo filter: {filter_error}")
                    
                    try:
                        await self.cuckoo_filter.add("username", username)
                    except Exception as filter_error:
                        logger.warning(f"Failed to add username to cuckoo filter: {filter_error}")

                    await conn.create(
                        "credentials", {**credentials, "user": result["id"]}
                    )

                    logger.debug(
                        json.dumps(result, option=json.OPT_INDENT_2, default=str)
                    )
                    return record_id_to_json(result)
                else:
                    logger.warning(
                        "User creation returned unexpected result: %s", result
                    )
                    return None
        except Exception as e:
            logger.error(f"Error creating user: {e}")
            return None

    async def delete_user_account(self, user_id: str) -> bool:
        """
        Delete a user account and all associated data.
        
        This method performs a comprehensive deletion of:
        - User record
        - Credentials
        - Events created by user
        - Posts, comments, and media
        - Tickets, friendships, and attendance records
        - Reports and livestream data
        
        Args:
            user_id: The ID of the user to delete
            
        Returns:
            bool: True if deletion succeeded, False otherwise
        """
        try:
            async with self.pool.acquire() as conn:
                # Get user email before deletion for Redis cleanup
                user_data = await conn.query(
                    "SELECT * FROM type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                if not user_data or not user_data[0]:
                    logger.warning(f"User {user_id} not found for deletion")
                    return False
                
                user_record = user_data[0]
                username = user_record.get("username")
                
                # Get encrypted email from credentials for Redis cleanup
                creds = await self.get_credentials(user_id)
                if creds and creds[0]:
                    email = await self.envelope_service.decrypt(
                        encrypted_data=creds[0]["encrypted_data"],
                        encrypted_dek=creds[0]["encrypted_decryption_key"],
                        data_initialization_vector=creds[0]["data_initialization_vector"],
                        decryption_key_initialization_vector=creds[0]["decryption_key_initialization_vector"],
                    )
                    email = email.decode() if isinstance(email, bytes) else email
                else:
                    email = None
                
                # Delete all user-related data using a transaction-like approach
                # Note: SurrealDB doesn't have traditional transactions, so we delete in order
                
                # 1. Delete credentials
                await conn.query(
                    "DELETE credentials WHERE user = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 2. Delete tickets
                await conn.query(
                    "DELETE tickets WHERE user = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 3. Delete attendance records
                await conn.query(
                    "DELETE attends WHERE in = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 4. Delete friendships (both directions)
                await conn.query(
                    "DELETE friends WHERE in = type::thing('users', $user_id) OR out = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 5. Delete comments
                await conn.query(
                    "DELETE comments WHERE in = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 6. Delete posts
                await conn.query(
                    "DELETE posts WHERE in = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 7. Delete reports made by user
                await conn.query(
                    "DELETE reports WHERE reporter = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 8. Get events created by user (to delete associated data)
                events = await conn.query(
                    "SELECT id FROM events WHERE host = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 9. Delete livestreams and scenes for user's events
                if events and events[0]:
                    for event in events[0]:
                        await conn.query(
                            "DELETE livestreams WHERE event = $event_id;",
                            {"event_id": event["id"]}
                        )
                        await conn.query(
                            "DELETE scenes WHERE event = $event_id;",
                            {"event_id": event["id"]}
                        )
                
                # 10. Delete has_media relations for user's events
                await conn.query(
                    "DELETE has_media WHERE in IN (SELECT id FROM events WHERE host = type::thing('users', $user_id));",
                    {"user_id": user_id}
                )
                
                # 11. Delete events created by user
                await conn.query(
                    "DELETE events WHERE host = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 12. Delete media uploaded by user
                await conn.query(
                    "DELETE media WHERE creator = type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # 13. Finally, delete the user record
                result = await conn.query(
                    "DELETE type::thing('users', $user_id);",
                    {"user_id": user_id}
                )
                
                # Clean up Redis cuckoo filter
                if email:
                    try:
                        await self.cuckoo_filter.delete("email", email)
                    except Exception as e:
                        logger.warning(f"Failed to remove email from cuckoo filter: {e}")
                
                if username:
                    try:
                        await self.cuckoo_filter.delete("username", username)
                    except Exception as e:
                        logger.warning(f"Failed to remove username from cuckoo filter: {e}")
                
                # Clean up any pending OTP records in Redis
                if email:
                    try:
                        await self.redis.delete(f"register-otp:{email}")
                        await self.redis.delete(f"forgot-password-otp:{email}")
                        await self.redis.delete(f"users:pending:{email}")
                    except Exception as e:
                        logger.warning(f"Failed to remove OTP records from Redis: {e}")
                
                logger.info(f"Successfully deleted user account: {user_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting user account {user_id}: {e}")
            return False
    
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


async def init_db(app) -> tuple[AuthDB, SurrealDBPoolManager]:
    """
    Initialize the database connection pool and return an AuthDB instance.

    Args:
        app: The Quart application instance

    Returns:
        tuple: Initialized database connector (AuthDB) and SurrealDBPoolManager
    """

    app.logger.debug("Initializing SurrealDB connection...")

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
    auth_db = AuthDB(pool, app.redis)

    return auth_db, pool_manager
