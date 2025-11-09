"""
Minimal reproduction for SurrealDB Python client Duration CBOR parsing bug
Issue: IndexError when parsing duration fields returned from queries
"""
import asyncio
from surrealdb import AsyncSurreal, Duration

async def reproduce_bug():
    """
    Demonstrates the CBOR parsing bug with duration fields
    """
    db = AsyncSurreal("ws://localhost:8000/rpc")
    await db.signin({"username": "root", "password": "rootrm"})
    await db.use("partyscene", "partyscene")
    
    print("Creating test event with duration field...")
    
    # Create a test event with duration
    try:
        await db.query("""
            CREATE test_event SET 
                title = "Test Event",
                time = time::now(),
                duration = 2h;
        """)
        print("✅ Event created successfully")
    except Exception as e:
        print(f"❌ Create failed: {e}")
    
    # Try to query it back
    print("\n1. Testing query() with duration field...")
    try:
        result = await db.query("SELECT * FROM test_event;")
        print(f"✅ Query succeeded: {result}")
    except Exception as e:
        print(f"❌ Query failed with {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    # Try select()
    print("\n2. Testing select() with duration field...")
    try:
        result = await db.query("SELECT VALUE id FROM test_event LIMIT 1;")
        if result and len(result) > 0 and len(result[0]) > 0:
            record_id = result[0][0]
            print(f"   Record ID: {record_id}")
            result = await db.select(record_id)
            print(f"✅ Select succeeded: {result}")
    except Exception as e:
        print(f"❌ Select failed with {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    
    # Show that omitting duration works
    print("\n3. Testing query with OMIT duration...")
    try:
        result = await db.query("SELECT * OMIT duration FROM test_event;")
        print(f"✅ Query with OMIT succeeded: {result}")
    except Exception as e:
        print(f"❌ Query with OMIT failed: {e}")
    
    # Cleanup
    print("\n4. Cleaning up...")
    try:
        await db.query("DELETE test_event;")
        print("✅ Cleanup complete")
    except:
        pass
    
    await db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("SurrealDB Python Client - Duration CBOR Parsing Bug")
    print("=" * 60)
    asyncio.run(reproduce_bug())
