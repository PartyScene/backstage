"""
Shared database utility functions for all microservices.
"""
from surrealdb import RecordID


async def report_resource(pool, data: dict, resource_table: str) -> dict:
    """
    Create a report for any resource type across all microservices.
    
    This is a DRY utility to avoid duplicating report logic across connectors.
    
    Args:
        pool: SurrealDB connection pool
        data (dict): Report data containing:
            - reporter: User ID who is reporting (will be converted to RecordID)
            - resource: Resource ID being reported (will be converted to RecordID)
            - reason: Reason for the report
        resource_table (str): Table name of the resource being reported 
                             (e.g., "users", "events", "scenes", "posts", "comments")
    
    Returns:
        dict: Created report record with IDs converted to strings
        
    Example:
        ```python
        report = await report_resource(
            pool=self.pool,
            data={
                "reporter": "user123",
                "resource": "event456", 
                "reason": "Inappropriate content"
            },
            resource_table="events"
        )
        ```
    """
    # Import here to avoid circular dependency
    from shared.utils import record_id_to_json
    
    # Convert string IDs to RecordIDs
    data["reporter"] = RecordID("users", data["reporter"])
    data["resource"] = RecordID(resource_table, data["resource"]) if not isinstance(data["resource"], RecordID) else data["resource"]
    
    # Create report in database
    async with pool.acquire() as conn:
        result = await conn.create("reports", data)
        return record_id_to_json(result)
