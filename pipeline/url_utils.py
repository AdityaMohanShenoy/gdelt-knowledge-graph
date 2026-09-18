from urllib.parse import SplitResult, urlsplit, urlunsplit


def normalize_url(value: str) -> str:
    raw = value.strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    hostname = parsed.hostname
    if not hostname:
        return ""
    normalized_hostname = hostname.lower()
    netloc = f"[{normalized_hostname}]" if ":" in normalized_hostname else normalized_hostname
    if parsed.username:
        netloc = parsed.username + (":" + parsed.password if parsed.password else "") + "@" + netloc
    if (
        port is not None
        and not (parsed.scheme.lower() == "http" and port == 80)
        and not (parsed.scheme.lower() == "https" and port == 443)
    ):
        netloc += f":{port}"
    normalized = SplitResult(
        parsed.scheme.lower(),
        netloc,
        parsed.path or "/",
        parsed.query,
        "",
    )
    return urlunsplit(normalized)
