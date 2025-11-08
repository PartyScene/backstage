from enum import StrEnum


class Microservice(StrEnum):
    AUTH = "AUTH"
    EVENTS = "EVENTS"
    POSTS = "POSTS"
    USERS = "USERS"
    MEDIA = "MEDIA"
    PAYMENTS = "PAYMENTS"
    R18E = "R18E"
    LIVESTREAM = "LIVESTREAM"

    def needs_rmq(self) -> bool:
        return self in (
            Microservice.MEDIA,
            Microservice.POSTS,
            Microservice.USERS,
            Microservice.EVENTS,
        )
