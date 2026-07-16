import hashlib


def calculate_analysis_input_hash(
    item_id: int,
    title: str,
    raw_text: str,
    source_url: str,
    model_name: str,
    prompt_version: str,
    analysis_version: str,
) -> str:
    parts = [
        str(item_id),
        title or "",
        raw_text or "",
        source_url or "",
        model_name or "",
        prompt_version or "",
        analysis_version or "",
    ]
    combined = "\x00".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()
