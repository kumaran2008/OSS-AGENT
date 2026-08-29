import json
import re


def is_valid_json_object(text: str) -> bool:
    """Used for planning/review outputs, which must be parseable JSON."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return False
    try:
        json.loads(match.group(0))
        return True
    except Exception:
        return False


def is_non_empty_code_block(text: str) -> bool:
    """Used for coding/debug outputs, which must contain a real code block."""
    match = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    if not match:
        return False
    return len(match.group(1).strip()) > 0
