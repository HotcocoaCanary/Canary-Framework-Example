ALLOWED_TRANSITIONS = {
    "pending": ["processing", "failed"],
    "processing": ["parsed", "failed"],
    "parsed": ["parsed", "chunked"],
    "chunked": [],
    "failed": ["processing"],
}

STATUS_ORDER = ["pending", "processing", "parsed", "chunked", "failed"]


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, [])


def can_edit_parsed(current: str) -> bool:
    return current == "parsed"


def can_chunk(current: str) -> bool:
    return current == "parsed"


def can_worker_process(current: str) -> bool:
    return current in ("pending", "failed")
