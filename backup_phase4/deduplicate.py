import hashlib
from datetime import datetime
from typing import Optional

def calculate_content_hash(
    source_id: int,
    url: str,
    normalized_title: str,
    published_at: Optional[datetime],
    external_id: Optional[str] = None
) -> str:
    # Детерминированное строковое представление даты
    pub_str = published_at.isoformat() if published_at else "None"
    
    if external_id:
        data_str = f"{source_id}|{external_id}|{url}|{normalized_title}|{pub_str}"
    else:
        data_str = f"{url}|{normalized_title}|{pub_str}"
        
    return hashlib.sha256(data_str.encode("utf-8")).hexdigest()
