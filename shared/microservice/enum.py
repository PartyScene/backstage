from enum import StrEnum


class Microservice(StrEnum):
    AUTH = "AUTH"
    EVENTS = "EVENTS"
    POSTS = "POSTS"
    USERS = "USERS"
    MEDIA = "MEDIA"
    LIVESTREAM = "LIVESTREAM"
    R18E = "R18E"

    def needs_rmq(self) -> bool:
        return self in (
            Microservice.MEDIA,
            Microservice.POSTS,
            Microservice.USERS,
            Microservice.LIVESTREAM,
            Microservice.EVENTS,
        )
