from dataclasses import dataclass


@dataclass
class FormIn:
    email: str
    first_name: str
    last_name: str
    password: str
