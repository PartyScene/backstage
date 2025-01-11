from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class Events(BaseModel):
    id: Optional[str] = None
    title: str
    description: str
    coordinates: tuple[int, int]
    is_live: bool
    is_private: bool
    host: str
    timestamp: Optional[datetime] = None
    price: str
    categories: List[str]
    tags: List[str]
