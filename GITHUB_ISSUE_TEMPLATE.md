## Bug: IndexError when parsing Duration fields from CBOR response

### Description
The SurrealDB Python client throws an `IndexError: list index out of range` when attempting to parse `duration` type fields returned from queries. This occurs in the CBOR decoder's `tag_decoder` function when processing duration values.

### Environment
- **surrealdb Python package version**: `0.3.2` (or your version)
- **Python version**: `3.13` (or your version)
- **SurrealDB server version**: `2.0.4` (or your version)
- **Operating System**: Windows/Linux/macOS

### Steps to Reproduce

1. Create a table with a `duration` field:
```python
import asyncio
from surrealdb import AsyncSurreal

async def reproduce():
    db = AsyncSurreal("ws://localhost:8000/rpc")
    await db.signin({"username": "root", "password": "root"})
    await db.use("test", "test")
    
    # Create record with duration
    await db.query("""
        CREATE test_table SET 
            name = "Test",
            event_duration = 2h;
    """)
    
    # Try to query it back - THIS FAILS
    result = await db.query("SELECT * FROM test_table;")
    print(result)
    
    await db.close()

asyncio.run(reproduce())
```

2. Run the script

### Expected Behavior
The query should successfully return records containing duration fields, with duration values properly parsed into Python `Duration` objects.

```python
# Expected output
[{'name': 'Test', 'event_duration': Duration(...)}]
```

### Actual Behavior
The query raises an `IndexError`:

```
Traceback (most recent call last):
  File "test.py", line 14, in reproduce
    result = await db.query("SELECT * FROM test_table;")
  File "/usr/local/lib/python3.13/site-packages/surrealdb/connections/async_ws.py", line 135, in query
    response = await self._send(message, "query")
  File "/usr/local/lib/python3.13/site-packages/surrealdb/connections/async_ws.py", line 61, in _send
    response = decode(await self.socket.recv())
  File "/usr/local/lib/python3.13/site-packages/surrealdb/data/cbor.py", line 141, in decode
    return cbor2.loads(data, tag_hook=tag_decoder)
  File "/usr/local/lib/python3.13/site-packages/surrealdb/data/cbor.py", line 120, in tag_decoder
    return Duration.parse(tag.value[0], tag.value[1])  # Two numbers (s, ns)
           ~~~~~~~~~^^^
IndexError: list index out of range
```

### Root Cause Analysis
The error occurs in `/surrealdb/data/cbor.py` at line 120:

```python
def tag_decoder(tag: CBORTag) -> Any:
    # ... other cases ...
    case 14:  # Duration
        return Duration.parse(tag.value[0], tag.value[1])  # ← Assumes 2-element list
```

The code expects `tag.value` to be a list with exactly 2 elements `[seconds, nanoseconds]`, but the actual CBOR-encoded duration from SurrealDB appears to have a different structure.

### Workaround
The only current workaround is to use `OMIT duration` in all queries:

```python
# This works
result = await db.query("SELECT * OMIT event_duration FROM test_table;")
```

### Impact
- **Severity**: High - Breaks all queries that return duration fields
- **Scope**: Affects both `query()` and `select()` methods
- **Production Impact**: Causes cascading connection failures when pooling is used

### Additional Context
This appears to be a mismatch between:
1. How SurrealDB server encodes `duration` values in CBOR
2. How the Python client expects to decode them

The CBOR tag handler assumes a 2-element array but receives something else. Adding debug logging to see the actual `tag.value` structure would help identify the correct parsing logic.

### Suggested Fix
Add defensive checks and better error messages in the CBOR decoder:

```python
case 14:  # Duration
    if not isinstance(tag.value, list):
        raise ValueError(f"Expected list for Duration tag, got {type(tag.value)}: {tag.value}")
    if len(tag.value) != 2:
        raise ValueError(f"Expected 2-element list for Duration, got {len(tag.value)} elements: {tag.value}")
    return Duration.parse(tag.value[0], tag.value[1])
```

This would at least provide clearer error messages to diagnose the actual format being received.

---

**Would appreciate any guidance on the correct CBOR format for duration values!** Happy to test fixes and provide more debug info if needed.
