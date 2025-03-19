from enum import StrEnum


class Microservice(StrEnum):
    AUTH = "AUTH"
    EVENTS = "EVENTS"
    POSTS = "POSTS"
    USERS = "USERS"
    MEDIA = "MEDIA"
    LIVESTREAM = "LIVESTREAM"
