```py
import time
from functools import wraps
from quart import request, current_app
from prometheus_client import Counter, Histogram, Gauge, Summary

# Define metrics
REQUEST_COUNT = Counter('request_count', 'App Request Count', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('request_latency_seconds', 'Request latency', ['method', 'endpoint'])
REQUESTS_IN_PROGRESS = Gauge('requests_in_progress', 'Requests in progress', ['method', 'endpoint'])
DB_QUERY_LATENCY = Histogram('db_query_latency_seconds', 'Database query latency')
REDIS_OPERATION_LATENCY = Histogram('redis_operation_latency_seconds', 'Redis operation latency')

def setup_metrics(app):
    """
    Setup metrics collection for a Quart app
    """
    @app.before_serving
    async def register_metrics_endpoint():
        from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
        
        @app.route('/metrics')
        async def metrics():
            return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}
    
    @app.before_request
    async def before_request():
        request.start_time = time.time()
        endpoint = request.path
        REQUESTS_IN_PROGRESS.labels(method=request.method, endpoint=endpoint).inc()
        
    @app.after_request
    async def after_request(response):
        endpoint = request.path
        resp_time = time.time() - request.start_time
        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(resp_time)
        REQUEST_COUNT.labels(method=request.method, endpoint=endpoint, status=response.status_code).inc()
        REQUESTS_IN_PROGRESS.labels(method=request.method, endpoint=endpoint).dec()
        return response

def track_db_query(func):
    """Decorator to track database query latency"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            return await func(*args, **kwargs)
        finally:
            DB_QUERY_LATENCY.observe(time.time() - start_time)
    return wrapper

def track_redis_operation(func):
    """Decorator to track Redis operation latency"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            return await func(*args, **kwargs)
        finally:
            REDIS_OPERATION_LATENCY.observe(time.time() - start_time)
    return wrapper```