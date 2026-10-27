"""Status service: a tiny HTTP app built to be run, scaled and observed in containers.

Endpoints: /  /api/hits  /healthz  /readyz  /metrics
"""
import json
import logging
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from redis_client import Redis, RedisError

INSTANCE = os.environ.get("INSTANCE_NAME") or socket.gethostname()
VERSION = os.environ.get("APP_VERSION", "dev")
STARTED = time.time()

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":%(message)s}')
log = logging.getLogger("status")


class Metrics:
    """Counters and a latency histogram rendered in Prometheus text format."""
    BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)

    def __init__(self):
        self.lock = threading.Lock()
        self.requests: dict[tuple[str, int], int] = {}
        self.buckets = [0] * (len(self.BUCKETS) + 1)
        self.sum = 0.0

    def observe(self, path: str, status: int, seconds: float) -> None:
        with self.lock:
            self.requests[(path, status)] = self.requests.get((path, status), 0) + 1
            self.sum += seconds
            for i, b in enumerate(self.BUCKETS):
                if seconds <= b:
                    self.buckets[i] += 1
            self.buckets[-1] += 1

    def render(self) -> str:
        with self.lock:
            lines = ["# HELP http_requests_total Requests by path and status.", "# TYPE http_requests_total counter"]
            lines += [f'http_requests_total{{path="{p}",status="{s}"}} {n}' for (p, s), n in sorted(self.requests.items())]
            lines += ["# HELP http_request_duration_seconds Request latency.", "# TYPE http_request_duration_seconds histogram"]
            lines += [f'http_request_duration_seconds_bucket{{le="{b}"}} {n}' for b, n in zip(self.BUCKETS, self.buckets)]
            lines += [f'http_request_duration_seconds_bucket{{le="+Inf"}} {self.buckets[-1]}',
                      f"http_request_duration_seconds_sum {self.sum:.6f}",
                      f"http_request_duration_seconds_count {self.buckets[-1]}",
                      f"process_uptime_seconds {time.time() - STARTED:.0f}",
                      f'app_info{{version="{VERSION}",instance="{INSTANCE}"}} 1']
        return "\n".join(lines) + "\n"


class App:
    def __init__(self, redis: Redis | None):
        self.redis = redis
        self.metrics = Metrics()
        self.local_hits = 0

    def hits(self) -> tuple[int, str]:
        if self.redis:
            try:
                return self.redis.incr("hits"), "redis"
            except (OSError, RedisError) as e:
                log.warning(json.dumps(f"redis unavailable: {e}"))
        self.local_hits += 1
        return self.local_hits, "memory"

    def ready(self) -> bool:
        if not self.redis:
            return True
        try:
            return self.redis.ping()
        except (OSError, RedisError):
            return False


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Status</title><style>body{{font:16px system-ui;max-width:560px;margin:60px auto;padding:0 16px}}code{{background:#eef;padding:2px 6px;border-radius:6px}}</style></head>
<body><h1>All systems go</h1><p>Served by <code>{instance}</code>, version <code>{version}</code>, up {uptime}s.</p>
<p>Refresh to watch nginx balance requests across replicas. Visit counter: <b id="h">…</b></p>
<script>fetch('/api/hits').then(r=>r.json()).then(j=>h.textContent=j.hits+' ('+j.store+', '+j.instance+')')</script></body></html>"""


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "status"
        sys_version = ""

        def _send(self, status: int, body: str, ctype: str = "application/json") -> None:
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Instance", INSTANCE)
            self.end_headers()
            self.wfile.write(data)
            self.status = status

        def do_GET(self):
            start = time.perf_counter()
            path = self.path.split("?")[0]
            if path == "/":
                self._send(200, PAGE.format(instance=INSTANCE, version=VERSION, uptime=int(time.time() - STARTED)), "text/html; charset=utf-8")
            elif path == "/api/hits":
                n, store = app.hits()
                self._send(200, json.dumps({"hits": n, "store": store, "instance": INSTANCE}))
            elif path == "/healthz":
                self._send(200, json.dumps({"status": "ok"}))
            elif path == "/readyz":
                ok = app.ready()
                self._send(200 if ok else 503, json.dumps({"ready": ok}))
            elif path == "/metrics":
                self._send(200, app.metrics.render(), "text/plain; version=0.0.4")
            else:
                self._send(404, json.dumps({"error": "not found"}))
            app.metrics.observe(path if path in {"/", "/api/hits", "/healthz", "/readyz", "/metrics"} else "other",
                                self.status, time.perf_counter() - start)

        def log_message(self, fmt, *args):
            log.info(json.dumps({"instance": INSTANCE, "client": self.client_address[0], "request": self.requestline, "status": int(args[1]) if len(args) > 1 and str(args[1]).isdigit() else 0}))

    return Handler


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    redis_host = os.environ.get("REDIS_HOST")
    app = App(Redis(redis_host, int(os.environ.get("REDIS_PORT", "6379"))) if redis_host else None)
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(app))
    # docker stop sends SIGTERM: finish in-flight requests, then exit cleanly.
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    log.info(json.dumps(f"{INSTANCE} listening on :{port} (redis={redis_host or 'off'})"))
    server.serve_forever()
    log.info(json.dumps("shut down cleanly"))


if __name__ == "__main__":
    main()
