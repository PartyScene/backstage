from .client import CloudflareLSClient


def create_livestream_client(app_instance, logger) -> CloudflareLSClient:
    """
    Factory function to create a Cloudflare Scenes Client instance
    Note: Call client.initialize() before first use (async method)
    
    Args:
        app_instance: Application instance
        logger: Logger instance
        
    Returns:
        CloudflareLSClient: Client instance (not yet initialized)
    """
    return CloudflareLSClient(app_instance, logger)
