"""
Test purreal connection and query to debug CancelledError
"""
import asyncio
import os
from purreal import SurrealDBPoolManager

async def test_query():
    """Test the fetch_public_events query that's failing in production"""
    
    # Create pool manager
    pool_manager = SurrealDBPoolManager()
    
    # Create connection pool
    pool = await pool_manager.create_pool(
        name="test_pool",
        uri="ws://localhost:8000/rpc",
        credentials={
            "username": "root",
            "password": "rootrm"
        },
        namespace="partyscene",
        database="partyscene",
        min_connections=3,
        max_connections=20,
        max_idle_time=60,
        connection_timeout=10.0,
        acquisition_timeout=30.0,
        health_check_interval=10,
        max_usage_count=100,
        connection_retry_attempts=3,
        connection_retry_delay=1.0,
        reset_on_return=True,
        log_queries=True,
    )
    
    print("✅ Pool created successfully")
    
    try:
        # Test 1: Simple query
        print("\n🔍 Test 1: Simple info query...")
        async with pool.acquire() as conn:
            result = await conn.query("INFO FOR DB;")
            print(f"✅ Simple query succeeded")
        
        # Test 2: The actual failing query
        print("\n🔍 Test 2: Fetch public events query...")
        async with pool.acquire() as conn:
            result = await conn.query(
                "RETURN fn::fetch_public_events($page, $limit);",
                {"page": 1, "limit": 50}
            )
            print(f"✅ Query succeeded! Got {len(result)} results")
            print(f"📊 Result preview: {result[:2] if result else 'empty'}")
        
        # Test 3: Run multiple queries concurrently (stress test)
        print("\n🔍 Test 3: Concurrent queries (10 simultaneous)...")
        async def run_query(i):
            try:
                async with pool.acquire() as conn:
                    result = await conn.query(
                        "RETURN fn::fetch_public_events($page, $limit);",
                        {"page": 1, "limit": 50}
                    )
                    print(f"  ✅ Query {i} succeeded")
                    return True
            except Exception as e:
                print(f"  ❌ Query {i} failed: {e}")
                return False
        
        tasks = [run_query(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in results if r is True)
        print(f"✅ Concurrent test: {success_count}/10 queries succeeded")
        
        # Test 4: Check pool stats
        print("\n📊 Pool Statistics:")
        stats = await pool.get_stats()
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        print("\n🧹 Closing pool...")
        await pool.close()
        print("✅ Test completed")

if __name__ == "__main__":
    asyncio.run(test_query())
