"""
Scheduled deletion cleanup job for processing account deletions after 30-day grace period.

This job should be run periodically (e.g., daily via cron job, Cloud Scheduler, or Kubernetes CronJob)
to process accounts that have passed their scheduled deletion date.

Usage:
    python -m auth.src.jobs.scheduled_deletion_cleanup
"""

import asyncio
import logging
import os
import sys
from datetime import datetime
from typing import List, Dict

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../..')))

from auth.src.connectors import AuthDB
from purreal import SurrealDBPoolManager
from redis.asyncio import Redis
import stripe

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


class ScheduledDeletionCleanup:
    """
    Background job to process scheduled account deletions.
    """
    
    def __init__(self, auth_db: AuthDB):
        self.auth_db = auth_db
    
    async def get_accounts_for_deletion(self) -> List[Dict]:
        """
        Fetch all user accounts scheduled for deletion where the deletion date has passed.
        
        Returns:
            List of user records to delete
        """
        try:
            query = """
                SELECT * FROM users 
                WHERE scheduled_deletion_at != NONE 
                AND scheduled_deletion_at <= time::now()
            """
            result = await self.auth_db.pool.execute_query(query)
            
            if result and isinstance(result, list):
                logger.info(f"Found {len(result)} accounts scheduled for deletion")
                return result
            
            return []
        
        except Exception as e:
            logger.error(f"Error fetching accounts for deletion: {e}")
            return []
    
    async def process_deletion(self, user_record: Dict) -> bool:
        """
        Process deletion for a single user account.
        
        Args:
            user_record: User record to delete
            
        Returns:
            True if deletion successful, False otherwise
        """
        user_id = user_record.get("id")
        
        if not user_id:
            logger.error(f"User record missing ID: {user_record}")
            return False
        
        # Extract user_id string from RecordID if needed
        if hasattr(user_id, 'id'):
            user_id = user_id.id
        elif isinstance(user_id, dict) and 'id' in user_id:
            user_id = user_id['id']
        elif isinstance(user_id, str) and ':' in user_id:
            user_id = user_id.split(':')[-1]
        
        logger.info(f"Processing deletion for user: {user_id}")
        
        try:
            # Delete Stripe account if exists
            stripe_account_id = user_record.get("stripe_account_id")
            if stripe_account_id:
                try:
                    await stripe.Account.delete_async(stripe_account_id)
                    logger.info(f"Deleted Stripe account: {stripe_account_id}")
                except stripe.StripeError as e:
                    logger.warning(f"Failed to delete Stripe account {stripe_account_id}: {e}")
            
            # Delete user account and all associated data
            deletion_result = await self.auth_db.delete_user_account(user_id)
            
            if deletion_result:
                logger.info(f"Successfully deleted user account: {user_id}")
                return True
            else:
                logger.error(f"Failed to delete user account: {user_id}")
                return False
        
        except Exception as e:
            logger.error(f"Error processing deletion for user {user_id}: {e}")
            return False
    
    async def run(self) -> Dict[str, int]:
        """
        Main execution method for the cleanup job.
        
        Returns:
            Dictionary with statistics about the cleanup run
        """
        logger.info("Starting scheduled deletion cleanup job")
        
        # Get accounts scheduled for deletion
        accounts = await self.get_accounts_for_deletion()
        
        stats = {
            "total_scheduled": len(accounts),
            "successful_deletions": 0,
            "failed_deletions": 0
        }
        
        # Process each account
        for user_record in accounts:
            success = await self.process_deletion(user_record)
            
            if success:
                stats["successful_deletions"] += 1
            else:
                stats["failed_deletions"] += 1
        
        logger.info(f"Cleanup job completed: {stats}")
        return stats


async def main():
    """
    Initialize database connection and run the cleanup job.
    """
    logger.info("Initializing scheduled deletion cleanup job")
    
    # Load environment variables
    SURREAL_URI = os.getenv("SURREAL_URI")
    SURREAL_USER = os.getenv("SURREAL_USER")
    SURREAL_PASS = os.getenv("SURREAL_PASS")
    REDIS_URI = os.getenv("REDIS_URI", "redis://localhost:6379")
    NAMESPACE = "partyscene"
    DATABASE = "partyscene"
    
    if not all([SURREAL_URI, SURREAL_USER, SURREAL_PASS]):
        logger.error("Missing required environment variables")
        sys.exit(1)
    
    # Create connection pool manager
    pool_manager = SurrealDBPoolManager()
    
    try:
        # Create Redis connection from URI
        redis = Redis.from_url(REDIS_URI, decode_responses=True)
        
        # Create connection pool
        pool = await pool_manager.create_pool(
            name="cleanup_pool",
            uri=SURREAL_URI,
            credentials={"username": SURREAL_USER, "password": SURREAL_PASS},
            namespace=NAMESPACE,
            database=DATABASE,
            min_connections=1,
            max_connections=3,
            max_idle_time=300,
            connection_timeout=5.0,
            acquisition_timeout=10.0,
        )
        
        # Create AuthDB instance
        auth_db = AuthDB(pool, redis)
        
        # Create and run cleanup job
        cleanup = ScheduledDeletionCleanup(auth_db)
        stats = await cleanup.run()
        
        logger.info(f"Cleanup job finished with stats: {stats}")
        
        # Close connections
        await redis.close()
        await pool_manager.close_all()
        
        # Exit with appropriate code
        if stats["failed_deletions"] > 0:
            sys.exit(1)  # Signal partial failure
        else:
            sys.exit(0)  # Success
    
    except Exception as e:
        logger.error(f"Fatal error in cleanup job: {e}")
        await pool_manager.close_all()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
