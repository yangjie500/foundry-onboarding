from uuid import UUID


def safe_request_id(event: object) -> str:
    """Return a canonical UUID request ID without trusting the event shape."""

    if not isinstance(event, dict):
        return "unknown"

    request_id = event.get("request_id")
    if not isinstance(request_id, str):
        return "unknown"

    try:
        return str(UUID(request_id))
    except ValueError:
        return "unknown"
