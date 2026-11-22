"""Small DeepSeek client with server-side web search."""

import ipaddress
import json
import urllib.parse
import http.client

REQUEST_TIMEOUT_SECONDS = 45.0
CHAT_COMPLETIONS_PATH = "/chat/completions"
MODEL = "deepseek-flash"
LOOPBACK_HOSTS = {"localhost", "LOCALHOST"}


class WebToolError(Exception):
    """Raised for any invalid input, transport problem, or unusable reply."""


def _is_loopback(host):
    if host.lower() in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_base_url(base_url):
    if not isinstance(base_url, str) or not base_url.strip():
        raise WebToolError("base_url must be a non-empty string")
    try:
        parsed = urllib.parse.urlsplit(base_url.strip())
    except ValueError:
        raise WebToolError("base_url is not a valid URL") from None
    if parsed.scheme not in ("http", "https"):
        raise WebToolError("base_url must use the http or https scheme")
    if not parsed.hostname:
        raise WebToolError("base_url must include a host")
    if parsed.username or parsed.password:
        raise WebToolError("base_url must not embed credentials")
    if parsed.query or parsed.fragment:
        raise WebToolError("base_url must not include a query or fragment")
    if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
        raise WebToolError("plain http is only allowed for loopback endpoints")
    return parsed


def _validate_inputs(base_url, api_key, messages):
    parsed = _validate_base_url(base_url)
    if not isinstance(api_key, str) or not api_key.strip():
        raise WebToolError("api_key must be a non-empty string")
    if not isinstance(messages, (list, tuple)) or not messages:
        raise WebToolError("messages must be a non-empty list")
    return parsed


def _post_chat_completion(parsed, api_key, body):
    path = parsed.path.rstrip("/") + CHAT_COMPLETIONS_PATH
    payload = json.dumps(body).encode("utf-8")
    host = parsed.hostname
    port = parsed.port
    if parsed.scheme == "https":
        conn = http.client.HTTPSConnection(
            host, port, timeout=REQUEST_TIMEOUT_SECONDS
        )
    else:
        conn = http.client.HTTPConnection(host, port, timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        conn.request(
            "POST",
            path,
            body=payload,
            headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
            },
        )
        response = conn.getresponse()
        status = response.status
        data = response.read()
    except OSError:
        raise WebToolError(
            "request to the chat endpoint failed or timed out"
        ) from None
    finally:
        conn.close()
    if 300 <= status < 400:
        raise WebToolError("redirect responses are not followed")
    if status != 200:
        raise WebToolError("chat endpoint returned error status {}".format(status))
    return data


def _extract_message(data):
    try:
        payload = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise WebToolError("chat endpoint returned a non-JSON body") from None
    if not isinstance(payload, dict):
        raise WebToolError("completion payload must be a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise WebToolError("completion payload contains no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise WebToolError("completion choice is malformed")
    message = first.get("message")
    if not isinstance(message, dict):
        raise WebToolError("completion choice contains no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise WebToolError("assistant message has no usable content")
    return message


def _check_search_status(message):
    steps = message.get("server_tool_calls")
    if steps is None:
        return
    if not isinstance(steps, list):
        raise WebToolError("server_tool_calls payload is malformed")
    for step in steps:
        if not isinstance(step, dict):
            raise WebToolError("server_tool_calls payload is malformed")
        calls = step.get("calls")
        if calls is None:
            continue
        if not isinstance(calls, list):
            raise WebToolError("server_tool_calls payload is malformed")
        for call in calls:
            if not isinstance(call, dict):
                raise WebToolError("server_tool_calls payload is malformed")
            status = call.get("status")
            if isinstance(status, str) and status.lower() == "failed":
                raise WebToolError(
                    "the server-side web search failed; refusing to present "
                    "its answer as a live-sourced reply"
                )


def _validate_citation_url(url):
    if not isinstance(url, str) or not url.strip():
        raise WebToolError("annotation citation is missing a url")
    try:
        parsed = urllib.parse.urlsplit(url.strip())
    except ValueError:
        raise WebToolError("annotation citation url is not a valid URL") from None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WebToolError(
            "annotation citation uses an unsafe url scheme: {!r}".format(url)
        )
    if not parsed.hostname:
        raise WebToolError("annotation citation url has no host")
    return url.strip()


def _build_sources(message):
    annotations = message.get("annotations")
    if annotations is None:
        return []
    if not isinstance(annotations, list):
        raise WebToolError("message annotations payload is malformed")
    sources = []
    for item in annotations:
        if not isinstance(item, dict):
            raise WebToolError("message annotation is malformed")
        citation = item.get("url_citation")
        if not isinstance(citation, dict):
            raise WebToolError("message annotation contains no url_citation")
        url = _validate_citation_url(citation.get("url"))
        title = citation.get("title")
        if title is not None and not isinstance(title, str):
            raise WebToolError("message annotation title is malformed")
        sources.append({"url": url, "title": title or ""})
    return sources


def _web_messages(messages):
    # DeepSeek Web Tools rejects assistant history before the first user turn.
    # A bounded history slice can begin mid-turn; keep storage unchanged.
    result = []
    seen_user = False
    for message in messages:
        role = message.get("role") if isinstance(message, dict) else None
        if role == "user":
            seen_user = True
        if role != "assistant" or seen_user:
            result.append(message)
    return result


def complete_web(base_url, api_key, messages):
    """One bounded Chat Completions request; returns (content, sources).

    ``sources`` may legitimately be empty when the model did not search or
    the server attached no citations; callers decide what to do with an
    unsourced answer.
    """
    parsed = _validate_inputs(base_url, api_key, messages)
    body = {
        "model": MODEL,
        "messages": _web_messages(messages),
        "tools": [{"type": "deepseek_web_search"}],
        "thinking": {"type": "disabled"},
    }
    data = _post_chat_completion(parsed, api_key, body)
    message = _extract_message(data)
    _check_search_status(message)
    sources = _build_sources(message)
    return message["content"], sources
