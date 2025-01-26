from pydantic import BaseModel, PositiveFloat
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

class Events(BaseModel):
    id: Optional[str] = None
    title: str
    description: str
    coordinates: List[float]  # Changed to List[float] to ensure proper serialization
    status: Optional[str] = None
    is_private: bool
    host: str
    timestamp: Optional[datetime] = None
    price: PositiveFloat
    categories: List[str]
    tags: List[str]
    metadata: Optional[Dict[str, Any]] = None
