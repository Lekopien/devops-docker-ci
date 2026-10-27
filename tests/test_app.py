import json
import socketserver
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from redis_client import Redis  # noqa: E402
from server import App, make_handler  # noqa: E402


class FakeRedis(socketserver.StreamRequestHandler):
    """Understands just enough RESP for PING and INCR."""
    counters: dict[str, int] = {}

    def handle(self):
        n = int(self.rfile.readline()[1:])
        args = []
        for _ in range(n):
            self.rfile.readline()
            args.append(self.rfile.readline().strip().decode())
        if args[0] == "PING":
            self.wfile.write(b"+PONG\r\n")
        elif args[0] == "INCR":
            self.counters[args[1]] = self.counters.get(args[1], 0) + 1
            self.wfile.write(b":%d\r\n" % self.counters[args[1]])
        else:
            self.wfile.write(b"-ERR unknown command\r\n")


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.redis = serve(socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeRedis))
        cls.with_redis = serve(ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(Redis(*cls.redis.server_address)))))
        cls.no_redis = serve(ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(None))))
        cls.dead_redis = serve(ThreadingHTTPServer(("127.0.0.1", 0), make_handler(App(Redis("127.0.0.1", 1)))))

    @classmethod
    def tearDownClass(cls):
        for s in (cls.redis, cls.with_redis, cls.no_redis, cls.dead_redis):
            s.shutdown()

    def get(self, server, path):
        url = f"http://127.0.0.1:{server.server_address[1]}{path}"
        try:
            with urllib.request.urlopen(url) as r:
                return r.status, r.read().decode(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(), e.headers

    def test_health_and_page(self):
        self.assertEqual(self.get(self.no_redis, "/healthz")[0], 200)
        status, body, headers = self.get(self.no_redis, "/")
        self.assertIn("All systems go", body)
        self.assertTrue(headers["X-Instance"])

    def test_hits_use_redis_and_fall_back(self):
        a = json.loads(self.get(self.with_redis, "/api/hits")[1])
        b = json.loads(self.get(self.with_redis, "/api/hits")[1])
        self.assertEqual((a["store"], b["hits"] - a["hits"]), ("redis", 1))
        self.assertEqual(json.loads(self.get(self.dead_redis, "/api/hits")[1])["store"], "memory")

    def test_readiness_reflects_redis(self):
        self.assertEqual(self.get(self.with_redis, "/readyz")[0], 200)
        self.assertEqual(self.get(self.dead_redis, "/readyz")[0], 503)

    def test_metrics_in_prometheus_format(self):
        self.get(self.no_redis, "/nope")
        status, body, headers = self.get(self.no_redis, "/metrics")
        self.assertTrue(headers["Content-Type"].startswith("text/plain"))
        self.assertIn('http_requests_total{path="other",status="404"} 1', body)
        self.assertIn('http_request_duration_seconds_bucket{le="+Inf"}', body)

    def test_redis_client_errors(self):
        from redis_client import RedisError
        with self.assertRaises(RedisError):
            Redis(*self.redis.server_address).command("FLY")


if __name__ == "__main__":
    unittest.main()
