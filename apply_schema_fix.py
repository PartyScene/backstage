"""
Apply schema fix to local database
"""
import asyncio
from surrealdb import AsyncSurreal

async def apply_fix():
    db = AsyncSurreal("ws://localhost:8000/rpc")
    await db.signin({"username": "root", "password": "rootrm"})
    await db.use("partyscene", "partyscene")
    
    print("Applying schema function updates (OMIT duration fix)...")
    
    # Update fn::fetch_event
    print("1. Updating fn::fetch_event...")
    try:
        await db.query("""
            DEFINE FUNCTION OVERWRITE fn::fetch_event($event_id: record) {
                RETURN (
                    SELECT
                    *,
                    (->has_media->media.{creator, metadata,  filename, url}) AS media,
                    <-attends<-users AS attendees,
                    host.{id, organization_name, first_name, last_name, avatar, filename, stripe_account_id}
                OMIT embeddings, duration
                FROM ONLY $event_id
                )
            };
        """)
        print("   ✅ fn::fetch_event updated")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Update fn::fetch_attended_events
    print("2. Updating fn::fetch_attended_events...")
    try:
        await db.query("""
            DEFINE FUNCTION OVERWRITE fn::fetch_attended_events($origin: record, $page: option<number>, $limit: option<number>) {
                LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
                LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

                LET $event_ids = (SELECT VALUE ->attends.out.id FROM ONLY $origin LIMIT $limit START ($page - 1) * $limit);

                RETURN array::map($event_ids, |$id| { fn::fetch_event($id) });
            };
        """)
        print("   ✅ fn::fetch_attended_events updated")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    # Update fn::fetch_created_events
    print("3. Updating fn::fetch_created_events...")
    try:
        await db.query("""
            DEFINE FUNCTION OVERWRITE fn::fetch_created_events($origin: record, $page: option<number>, $limit: option<number>) {
                LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
                LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

                RETURN (
                    SELECT * OMIT duration FROM events WHERE creator = $origin
                    LIMIT $limit START ($page - 1) * $limit
                )
            };
        """)
        print("   ✅ fn::fetch_created_events updated")
    except Exception as e:
        print(f"   ❌ Failed: {e}")
    
    print("\n✅ All schema updates applied successfully")
    
    await db.close()

asyncio.run(apply_fix())
