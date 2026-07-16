import re
from typing import Dict, List

# Регулярные выражения для поиска сущностей
GITHUB_REGEX = r"github\.com/([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)"
HF_DATASET_REGEX = r"huggingface\.co/datasets/([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)"
HF_SPACE_REGEX = r"huggingface\.co/spaces/([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)"
HF_MODEL_REGEX = r"huggingface\.co/(?!(?:datasets|spaces|blog|docs|chat|settings|join|login)/)([a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+)"
ARXIV_REGEX = r"(?:arxiv\.org/(?:abs|pdf)/|arxiv:)(\d{4}\.\d{4,5})"
DOI_REGEX = r"doi\.org/(10\.\d{4,9}/[-._;()/:A-Z0-9]+)"
YOUTUBE_REGEX = r"(?:youtube\.cn|youtube\.com/watch\?v=|youtu\.be/)([a-zA-Z0-9_-]{11})"
VERSION_REGEX = r"\b(?:v|version\s+)(\d+\.\d+(?:\.\d+)?)\b"

def extract_entity_keys(text: str) -> Dict[str, List[str]]:
    result = {
        "github_repositories": [],
        "huggingface_models": [],
        "huggingface_datasets": [],
        "huggingface_spaces": [],
        "arxiv_ids": [],
        "dois": [],
        "youtube_ids": [],
        "version_tokens": []
    }
    
    if not text:
        return result

    # 1. GitHub
    def clean_val(v: str) -> str:
        return v.rstrip(".,?!:;/-")

    # 1. GitHub
    for match in re.finditer(GITHUB_REGEX, text, re.IGNORECASE):
        repo = clean_val(match.group(1).rstrip(".git"))
        # Исключаем служебные пути
        if not repo.startswith(("features", "pricing", "trending", "marketplace")):
            result["github_repositories"].append(repo)
            
    # 2. Hugging Face Datasets
    for match in re.finditer(HF_DATASET_REGEX, text, re.IGNORECASE):
        result["huggingface_datasets"].append(clean_val(match.group(1)))
        
    # 3. Hugging Face Spaces
    for match in re.finditer(HF_SPACE_REGEX, text, re.IGNORECASE):
        result["huggingface_spaces"].append(clean_val(match.group(1)))
        
    # 4. Hugging Face Models
    for match in re.finditer(HF_MODEL_REGEX, text, re.IGNORECASE):
        result["huggingface_models"].append(clean_val(match.group(1)))
        
    # 5. arXiv
    for match in re.finditer(ARXIV_REGEX, text, re.IGNORECASE):
        result["arxiv_ids"].append(clean_val(match.group(1)))
        
    # 6. DOI
    for match in re.finditer(DOI_REGEX, text, re.IGNORECASE):
        result["dois"].append(clean_val(match.group(1)))
        
    # 7. YouTube
    for match in re.finditer(YOUTUBE_REGEX, text, re.IGNORECASE):
        result["youtube_ids"].append(clean_val(match.group(1)))
        
    # 8. Version tokens
    for match in re.finditer(VERSION_REGEX, text, re.IGNORECASE):
        result["version_tokens"].append(clean_val(match.group(1)))

    # Дедуплицируем списки с сохранением порядка
    for k in result:
        result[k] = list(dict.fromkeys(result[k]))
        
    return result
