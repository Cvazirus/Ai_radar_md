import re
import json


class InvalidJSONError(Exception):
    pass


def extract_json_object(raw_response: str) -> dict:
    if not raw_response or not raw_response.strip():
        raise InvalidJSONError("Empty response")

    text = raw_response.strip()

    # Strip code fences
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    # Reject eval-like constructs
    if re.search(r'\beval\s*\(', text, re.IGNORECASE):
        raise InvalidJSONError("eval-like construct detected")

    # Find the first '{' and last '}'
    first_brace = text.find('{')
    last_brace = text.rfind('}')

    if first_brace == -1 or last_brace == -1:
        raise InvalidJSONError("No JSON object braces found")

    # Check no text before '{' (except whitespace which is already stripped)
    # and no text after '}' (except whitespace which is already stripped)
    prefix = text[:first_brace].strip()
    suffix = text[last_brace + 1:].strip()

    if prefix:
        raise InvalidJSONError(f"Text before JSON object: {prefix[:100]}")
    if suffix:
        raise InvalidJSONError(f"Text after JSON object: {suffix[:100]}")

    candidate = text[first_brace:last_brace + 1]

    # Check for multiple objects
    if candidate.count('{') > 1:
        # Verify it's not nested
        depth = 0
        found_close = False
        for ch in candidate:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    found_close = True
                    break
        if not found_close:
            raise InvalidJSONError("Unclosed JSON object")
        # If we found close at depth 0 before end, there's extra content
        remaining = candidate[candidate.find('}', candidate.find('{')) + 1:].strip()
        # Actually just try to parse it
        pass

    try:
        result = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise InvalidJSONError(f"Invalid JSON: {e}")

    if not isinstance(result, dict):
        raise InvalidJSONError(f"Expected object, got {type(result).__name__}")

    return result
