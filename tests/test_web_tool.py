"""Tests for ``venus.web_tool.complete_web`` (test-first specification).

Contract under test:

    complete_web(base_url, api_key, messages) -> (content, sources)

* Calls a DeepSeek-compatible Chat Completions endpoint (``/chat/completions``)
  with ``model == "deepseek-flash"``, ``tools == [{"type": "deepseek_web_search"}]``
  and thinking disabled, preserving the persona/system and user context
  messages unchanged in order.
* Returns ``(content, sources)`` where ``sources`` is built ONLY from
  server-provided web-search annotations (never invented, never scraped out
  of the model text).
* Validates annotations: unsafe (non http/https) URLs, an empty/failed web
  search presented as a live answer, redirect responses, error statuses and
  malformed payloads all raise ``web_tool.WebToolError``.
* Rejects non-HTTPS, non-loopback ``base_url`` endpoints and blank inputs.
* Every request is time bounded: an unresponsive server must not hang the
  caller forever.

Hard test constraints honoured here: all traffic goes to an in-process fake
HTTP server bound to 127.0.0.1 on an ephemeral port (plus one unresolvable
documentation-range IP used only to prove rejection happens *before* any
network attempt). Keys are obviously fake. Nothing real is contacted and no
environment variables or secrets are read.
"""

import json
import threading
import time
import unittest
from unittest.mock import patch
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from venus import web_tool

FAKE_API_KEY = "sk-fake-test-key-0123456789abcdef"

# How long the fake server withholds a response in the time-bound test.
HOLD_SECONDS = 20
# The call must surface an error (or otherwise return) well within this.
CALL_BOUND_SECONDS = 8

PERSONA_MESSAGES = [
    {"role": "system", "content": "你是 Venus，一个温柔但好奇的伙伴。"},
    {"role": "user", "content": "今天天气怎么样？"},
]


def annotation(url, title="t"):
    return {"type": "url_citation", "url_citation": {"url": url, "title": title}}


def completion(content="好的", annotations=None, server_tool_calls=None):
    """Build a DeepSeek-style chat.completion payload."""
    message = {"role": "assistant", "content": content}
    if annotations is not None:
        message["annotations"] = annotations
    if server_tool_calls is not None:
        message["server_tool_calls"] = server_tool_calls
    return {
        "id": "chatcmpl-fake-0001",
        "object": "chat.completion",
        "model": "deepseek-flash",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
    }


def web_search_call(status):
    return [{"index": 0, "calls": [{"index": 0, "id": "ws-fake-0001", "type": "deepseek_web_search", "kind": "search", "action": {"type": "search", "queries": ["test"]}, "status": status}]}]


class _RecordingHandler(BaseHTTPRequestHandler):
    def _record(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = raw
        with self.server.fake.lock:
            self.server.fake.requests.append(
                {
                    "method": method,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                }
            )
        status, payload, extra_headers, delay = self.server.fake.responses.popleft()
        if delay:
            time.sleep(delay)
        data = b"" if payload is None else payload
        if not isinstance(data, bytes):
            data = json.dumps(data).encode("utf-8")
        self.send_response(status)
        for key, value in extra_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self._record("POST")

    def do_GET(self):
        self._record("GET")

    def log_message(self, fmt, *args):  # keep test output quiet
        pass


class FakeDeepSeekServer:
    """Loopback-only stand-in for the DeepSeek Chat Completions API."""

    def __init__(self):
        self.requests = []
        self.responses = deque()
        self.lock = threading.Lock()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.httpd.fake = self
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        host, port = self.httpd.server_address[:2]
        return "http://{}:{}".format(host, port)

    def queue_json(self, status=200, payload=None, extra_headers=None, delay=0.0):
        self.responses.append((status, payload, dict(extra_headers or {}), delay))

    def wait_until_drained(self, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if not self.responses:
                    return True
            time.sleep(0.02)
        return not self.responses

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class WebToolTestBase(unittest.TestCase):
    def setUp(self):
        self.server = FakeDeepSeekServer()
        self.addCleanup(self.server.stop)

    def call(self, messages=None, base_url=None, api_key=FAKE_API_KEY):
        return web_tool.complete_web(
            base_url or self.server.base_url,
            api_key,
            PERSONA_MESSAGES if messages is None else messages,
        )

    def assert_one_chat_request(self):
        self.assertEqual(len(self.server.requests), 1, "expected exactly one HTTP request")
        self.assertIn("/chat/completions", self.server.requests[0]["path"])
        self.assertTrue(self.server.wait_until_drained(), "unused queued responses")
        request = self.server.requests[0]
        self.server.requests.clear()
        return request


class RequestContractTests(WebToolTestBase):
    def test_blank_inputs_rejected_without_any_request(self):
        for bad in ("", "   ", None):
            with self.subTest(base_url=bad):
                with self.assertRaises(web_tool.WebToolError):
                    web_tool.complete_web(bad, FAKE_API_KEY, PERSONA_MESSAGES)
        for bad in ("", "   ", None):
            with self.subTest(api_key=bad):
                with self.assertRaises(web_tool.WebToolError):
                    web_tool.complete_web(self.server.base_url, bad, PERSONA_MESSAGES)
        with self.assertRaises(web_tool.WebToolError):
            web_tool.complete_web(self.server.base_url, FAKE_API_KEY, [])
        self.assertEqual(self.server.requests, [], "no HTTP request may be attempted")

    def test_non_https_non_loopback_endpoint_rejected_before_network(self):
        # 198.51.100.7 is TEST-NET-2 documentation space: unreachable by
        # design. A validating client must reject it offline, fast.
        for bad in (
            "http://198.51.100.7:8000",
            "http://198.51.100.7",
            "ftp://198.51.100.7",
            "198.51.100.7:8000",
        ):
            with self.subTest(base_url=bad):
                started = time.monotonic()
                with self.assertRaises(web_tool.WebToolError):
                    web_tool.complete_web(bad, FAKE_API_KEY, PERSONA_MESSAGES)
                self.assertLess(
                    time.monotonic() - started,
                    2.0,
                    "rejection must be a validation step, not a network attempt",
                )

    def test_plain_http_loopback_is_accepted(self):
        self.server.queue_json(payload=completion())
        content, sources = self.call()
        self.assertEqual(content, "好的")
        self.assertEqual(sources, [])
        self.assert_one_chat_request()

    def test_request_targets_deepseek_flash_with_web_search_tool_and_thinking_off(self):
        self.server.queue_json(payload=completion())
        self.call(api_key=FAKE_API_KEY)
        req = self.assert_one_chat_request()
        self.assertEqual(req["headers"].get("authorization"), "Bearer " + FAKE_API_KEY)
        body = req["body"]
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(
            [tool.get("type") for tool in body["tools"]], ["deepseek_web_search"]
        )
        thinking = body.get("thinking")
        self.assertIsInstance(thinking, dict, "thinking parameter must be sent explicitly")
        self.assertEqual(thinking.get("type"), "disabled")

    def test_truncated_history_drops_only_leading_assistant_entries(self):
        system = PERSONA_MESSAGES[0]
        background = {"role": "system", "content": "虚构背景"}
        orphan = {"role": "assistant", "content": "被历史上限截断的旧回复"}
        proactive = {"role": "assistant", "content": "上一条主动聊天"}
        user = PERSONA_MESSAGES[1]
        reply = {"role": "assistant", "content": "回答"}
        current = {"role": "user", "content": "继续聊吧"}
        messages = [system, background, orphan, proactive, user, reply, proactive, current]
        original = [dict(message) for message in messages]
        self.server.queue_json(payload=completion())
        self.call(messages=messages)
        sent = self.assert_one_chat_request()["body"]["messages"]
        self.assertEqual(sent, [system, background, user, reply, proactive, current])
        self.assertEqual(messages, original)

    def test_persona_and_user_context_messages_preserved_in_order(self):
        self.server.queue_json(payload=completion())
        self.call(messages=PERSONA_MESSAGES)
        sent = self.assert_one_chat_request()["body"]["messages"]
        self.assertEqual(sent[: len(PERSONA_MESSAGES)], PERSONA_MESSAGES)


class ResponseContractTests(WebToolTestBase):
    def test_returns_content_and_sources_from_server_annotations(self):
        self.server.queue_json(
            payload=completion(
                content="根据搜索结果……",
                annotations=[
                    annotation("https://example.org/a", title="来源A"),
                    annotation("https://example.net/b", title="来源B"),
                ],
                server_tool_calls=web_search_call("completed"),
            )
        )
        content, sources = self.call()
        self.assertEqual(content, "根据搜索结果……")
        self.assertEqual(
            [s["url"] for s in sources],
            ["https://example.org/a", "https://example.net/b"],
        )
        self.assertEqual([s["title"] for s in sources], ["来源A", "来源B"])
        self.assert_one_chat_request()

    def test_loopback_http_annotation_urls_are_accepted(self):
        url = self.server.base_url + "/page"
        self.server.queue_json(
            payload=completion(annotations=[annotation(url)], server_tool_calls=web_search_call("completed"))
        )
        _, sources = self.call()
        self.assertEqual([s["url"] for s in sources], [url])
        self.assert_one_chat_request()

    def test_source_links_are_never_invented_from_content_text(self):
        # The model text mentions a URL, but the server attached no
        # annotation: sources must stay empty.
        self.server.queue_json(
            payload=completion(
                content="详见 https://example.com/mentioned",
                annotations=[],
                server_tool_calls=web_search_call("completed"),
            )
        )
        _, sources = self.call()
        self.assertEqual(sources, [])
        self.assert_one_chat_request()

    def test_unsafe_annotation_url_scheme_rejected(self):
        for bad_url in (
            "javascript:alert(1)",
            "data:text/html;base64,PHNjcmlwdD4=",
            "file:///C:/Windows/win.ini",
            "not-a-url",
        ):
            with self.subTest(url=bad_url):
                self.server.queue_json(
                    payload=completion(
                        annotations=[annotation(bad_url)],
                        server_tool_calls=web_search_call("completed"),
                    )
                )
                with self.assertRaises(web_tool.WebToolError):
                    self.call()
                self.assert_one_chat_request()

    def test_failed_web_search_is_not_misrepresented(self):
        # Search failed server-side; any "answer" must not be surfaced as a
        # live-sourced reply.
        self.server.queue_json(
            payload=completion(
                content="我联网查到了……（其实没有）",
                annotations=[],
                server_tool_calls=web_search_call("failed"),
            )
        )
        with self.assertRaises(web_tool.WebToolError):
            self.call()
        self.assert_one_chat_request()

    def test_empty_or_malformed_completion_rejected(self):
        malformed = [
            {"id": "x", "choices": []},
            {"id": "x", "choices": [{"index": 0, "message": {"role": "assistant"}}]},
            {"id": "x", "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}}]},
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                self.server.queue_json(payload=payload)
                with self.assertRaises(web_tool.WebToolError):
                    self.call()
                self.assert_one_chat_request()

    def test_non_json_body_rejected(self):
        self.server.queue_json(payload=b"<html>gateway said no</html>")
        with self.assertRaises(web_tool.WebToolError):
            self.call()
        self.assert_one_chat_request()

    def test_error_status_rejected(self):
        for status in (401, 429, 500):
            with self.subTest(status=status):
                self.server.queue_json(
                    status=status, payload={"error": {"message": "nope", "type": "upstream"}}
                )
                with self.assertRaises(web_tool.WebToolError):
                    self.call()
                self.assert_one_chat_request()

    def test_redirect_rejected_without_following(self):
        self.server.queue_json(
            status=302,
            payload=None,
            extra_headers={"Location": self.server.base_url + "/moved"},
        )
        with self.assertRaises(web_tool.WebToolError):
            self.call()
        # A client that followed the redirect would have produced a second
        # recorded request on the fake server.
        self.assertEqual(len(self.server.requests), 1, "redirect must not be followed")
        self.assertTrue(self.server.wait_until_drained())


class TimeBoundTests(unittest.TestCase):
    def test_unresponsive_server_does_not_hang_caller(self):
        server = FakeDeepSeekServer()
        self.addCleanup(server.stop)
        server.queue_json(payload=completion(), delay=HOLD_SECONDS)

        outcome = {}

        def run():
            try:
                with patch.object(web_tool, 'REQUEST_TIMEOUT_SECONDS', 0.5):
                    outcome["result"] = web_tool.complete_web(
                        server.base_url, FAKE_API_KEY, PERSONA_MESSAGES
                    )
            except BaseException as exc:  # noqa: BLE001 - captured for assertion
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        started = time.monotonic()
        worker.start()
        worker.join(CALL_BOUND_SECONDS)
        elapsed = time.monotonic() - started

        self.assertFalse(
            worker.is_alive(),
            "complete_web must abandon an unresponsive endpoint within its time bound",
        )
        self.assertLess(elapsed, CALL_BOUND_SECONDS)
        self.assertIsInstance(
            outcome.get("error"),
            web_tool.WebToolError,
            "a timed-out call must raise WebToolError, not return a fake success",
        )


if __name__ == "__main__":
    unittest.main()
