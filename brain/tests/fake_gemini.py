"""A local stand-in for the Gemini REST API (feature 005, T007; research R-13).

The real `google-genai` SDK is pointed at it through `BRAIN_GEMINI_BASE_URL`, so the adapter's
request building, response parsing and error mapping are tested without the network. Scripted
answers are served in order; every request is recorded (path, headers, JSON body) so tests can
count attempts and check where the API key went.
"""

import json
import socket
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CANARY_KEY = "test-canary-key-7f3a"


def text(value: str) -> dict[str, Any]:
    return {
        "status": 200,
        "json": {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": value}]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ]
        },
    }


def function_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": 200,
        "json": {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {"name": name, "args": args},
                                "thoughtSignature": "c2lnbmF0dXJl",
                            }
                        ],
                    },
                    "finishReason": "STOP",
                    "index": 0,
                }
            ]
        },
    }


def error(status: int, google_status: str = "", reason: str = "") -> dict[str, Any]:
    details = (
        [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}] if reason else []
    )
    return {
        "status": status,
        "json": {
            "error": {
                "code": status,
                "message": f"fake error {status} (this text must never reach the Brain's screens)",
                "status": google_status or "UNKNOWN",
                "details": details,
            }
        },
    }


def empty() -> dict[str, Any]:
    return {"status": 200, "json": {"candidates": []}}


def safety() -> dict[str, Any]:
    return {"status": 200, "json": {"candidates": [{"finishReason": "SAFETY", "index": 0}]}}


def slow(seconds: float, answer: dict[str, Any] | None = None) -> dict[str, Any]:
    return {**(answer or text("late")), "delay": seconds}


class FakeGemini:
    def __init__(self) -> None:
        self.generate: deque[dict[str, Any]] = deque()
        self.probe: deque[dict[str, Any]] = deque()
        self.requests: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:  # keep test output clean
                return

            def _answer(self, queue: deque[dict[str, Any]], default: dict[str, Any]) -> None:
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length) if length else b""
                with fake._lock:
                    fake.requests.append(
                        {
                            "method": self.command,
                            "path": self.path,
                            "headers": {k.lower(): v for k, v in self.headers.items()},
                            "body": json.loads(raw) if raw else None,
                        }
                    )
                    answer = queue.popleft() if queue else default
                if answer.get("delay"):
                    time.sleep(answer["delay"])
                payload = json.dumps(answer["json"]).encode()
                try:
                    self.send_response(answer["status"])
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass  # the client gave up (a timeout test)

            def do_POST(self) -> None:
                self._answer(fake.generate, text("default fake reply"))

            def do_GET(self) -> None:
                name = self.path.split("?")[0].rsplit("/", 1)[-1]
                self._answer(
                    fake.probe,
                    {"status": 200, "json": {"name": f"models/{name}", "displayName": name}},
                )

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._silent: socket.socket | None = None
        self._silent_conns: list[socket.socket] = []

    # ---- scripting
    def answer(self, *answers: dict[str, Any]) -> None:
        self.generate.extend(answers)

    def answer_probe(self, *answers: dict[str, Any]) -> None:
        self.probe.extend(answers)

    def generate_requests(self) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["method"] == "POST"]

    # ---- unreachable variants
    @staticmethod
    def closed_port_url() -> str:
        """A port with no listener: the connection is refused at once."""
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def silent_url(self) -> str:
        """A socket that accepts connections and never sends a byte."""
        if self._silent is None:
            self._silent = socket.socket()
            self._silent.bind(("127.0.0.1", 0))
            self._silent.listen(16)

            def accept() -> None:
                while True:
                    try:
                        conn, _ = self._silent.accept()  # type: ignore[union-attr]
                    except OSError:
                        return
                    self._silent_conns.append(conn)

            threading.Thread(target=accept, daemon=True).start()
        return f"http://127.0.0.1:{self._silent.getsockname()[1]}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        if self._silent is not None:
            self._silent.close()
        for conn in self._silent_conns:
            conn.close()
