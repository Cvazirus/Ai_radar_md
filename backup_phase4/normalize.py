import html
import re
from datetime import datetime, timezone
from typing import Optional
from bs4 import BeautifulSoup

def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    # Декодируем html entities
    title = html.unescape(title)
    # Удаляем HTML теги
    title = re.sub(r'<[^>]+>', '', title)
    # Убираем лишние пробелы
    title = " ".join(title.split())
    return title

def normalize_text(text_content: Optional[str]) -> Optional[str]:
    if not text_content:
        return None
        
    try:
        # Используем BeautifulSoup для чистки HTML
        soup = BeautifulSoup(text_content, "html.parser")
        
        # Удаляем скрипты и стили
        for element in soup(["script", "style"]):
            element.decompose()
            
        # Получаем текст
        cleaned_text = soup.get_text(separator=" ")
        # Декодируем entities
        cleaned_text = html.unescape(cleaned_text)
        # Убираем повторяющиеся пробелы и переносы
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
        cleaned_text = cleaned_text.strip()
        
        return cleaned_text if cleaned_text else None
    except Exception:
        # Фолбэк на регулярные выражения, если суп упал
        cleaned = re.sub(r'<[^>]+>', ' ', text_content)
        cleaned = html.unescape(cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        return cleaned if cleaned else None

def normalize_author(author: Optional[str]) -> Optional[str]:
    if not author:
        return None
    cleaned = " ".join(author.split())
    return cleaned if cleaned else None

def normalize_published_at(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    # Приводим к UTC
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def normalize_language(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    # Эвристика: если есть кириллица, то русский, иначе английский
    cyrillic_chars = len(re.findall(r'[а-яА-ЯёЁ]', text))
    if cyrillic_chars > 10:
        return "ru"
    return "en"
