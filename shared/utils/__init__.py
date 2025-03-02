from .client import MediaClient


def create_media_client(media_service_url: str) -> MediaClient:
    """Factory function to create a MediaClient instance"""
    return MediaClient(media_service_url)
