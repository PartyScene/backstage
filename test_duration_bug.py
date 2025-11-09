"""
Test to investigate the Duration parsing bug
"""
import asyncio
from surrealdb import AsyncSurreal

async def test():
    db = AsyncSurreal("ws://localhost:8000/rpc")
    await db.signin({"username": "root", "password": "rootrm"})
    await db.use("partyscene", "partyscene")
    
    # Query events directly without using the function
    print("Querying events directly...")
    try:
        result = await db.query("SELECT * FROM events LIMIT 1;")
        print(f"✅ Direct query succeeded: {result}")
    except Exception as e:
        print(f"❌ Direct query failed: {e}")
    
    # Try to query just the duration field
    print("\nQuerying just duration field...")
    try:
        result = await db.query("SELECT duration FROM events LIMIT 1;")
        print(f"✅ Duration query succeeded: {result}")
    except Exception as e:
        print(f"❌ Duration query failed: {e}")
    
    # Query without duration
    print("\nQuerying without duration field...")
    try:
        result = await db.query("SELECT * OMIT duration FROM events LIMIT 1;")
        print(f"✅ Query without duration succeeded: {result}")
    except Exception as e:
        print(f"❌ Query without duration failed: {e}")
    
    await db.close()

asyncio.run(test())
