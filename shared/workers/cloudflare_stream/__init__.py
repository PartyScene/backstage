from .client import CloudflareLSClient


def create_livestream_client(app_instance, logger) -> CloudflareLSClient:
    """Factory function to create a Cloudflare Scenes Client instance"""
    return CloudflareLSClient(app_instance, logger)
