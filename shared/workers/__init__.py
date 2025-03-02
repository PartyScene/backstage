from .client import LSClient


def create_livestream_client(database_instance, logger) -> LSClient:
    """Factory function to create a LiveStream Client instance"""
    return LSClient(database_instance, logger)
