import hashlib
import html
import re
from datetime import datetime
from typing import Optional
from difflib import SequenceMatcher

PREFIX_REGEX = re.compile(
    r"^(?:show\s+hn|hn|habr|blog|openai|google|hugging\s+face|arxiv|pdf|video|news|press\s+release|update|release):\s*",
    re.IGNORECASE
)

# Регулярка для поиска Part 1, Episode 3, Chapter 4, #5, Update 2, v1.2 и т.д.
PART_MARKER_REGEX = re.compile(
    r"\b(?:part|episode|chapter|version|update|v|#|выпуск|часть)\s*[-#:]?\s*(\d+(?:\.\d+)*)\b",
    re.IGNORECASE
)

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

def normalize_title_for_matching(title: str) -> str:
    if not title:
        return ""
    
    # 1. HTML unescape
    title = html.unescape(title)
    
    # 2. Lowercase
    title = title.lower()
    
    # 3. Remove source prefixes
    title = PREFIX_REGEX.sub("", title)
    
    # 4. Replace punctuation, quotes, dashes with space, preserving decimals in numbers
    title = re.sub(r"[-'\"`«»„“()\[\]{}!?,;:—–#*&]", " ", title)
    title = re.compile(r"(?<!\d)\.|\.(?!\d)").sub(" ", title)
    
    # 5. Collapse spaces
    title = " ".join(title.split())
    
    return title

def calculate_title_similarity(title1: str, title2: str) -> float:
    t1_norm = normalize_title_for_matching(title1)
    t2_norm = normalize_title_for_matching(title2)
    if not t1_norm or not t2_norm:
        return 0.0
    return SequenceMatcher(None, t1_norm, t2_norm).ratio()

def extract_part_marker(title: str) -> Optional[str]:
    if not title:
        return None
    matches = PART_MARKER_REGEX.findall(title)
    if matches:
        return matches[0]
    return None

def has_mismatched_parts(title1: str, title2: str) -> bool:
    m1 = extract_part_marker(title1)
    m2 = extract_part_marker(title2)
    # Если оба маркера есть и они не равны, то это несовпадение частей
    if m1 is not None and m2 is not None and m1 != m2:
        return True
    return False
