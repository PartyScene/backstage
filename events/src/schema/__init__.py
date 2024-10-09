from dataclasses import dataclass


@dataclass
class Events:
    id: str
    is_live: bool
    location: tuple
    name: str
    organizer: str
    price: str
