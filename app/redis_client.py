"""A minimal Redis client speaking the RESP protocol over a socket (no redis-py needed)."""
import socket


class RedisError(Exception):
    pass


class Redis:
    def __init__(self, host: str = "localhost", port: int = 6379, timeout: float = 1.0):
        self.addr = (host, port)
        self.timeout = timeout

    def command(self, *args: str | int):
        payload = f"*{len(args)}\r\n".encode()
        for a in args:
            b = str(a).encode()
            payload += b"$%d\r\n%s\r\n" % (len(b), b)
        with socket.create_connection(self.addr, timeout=self.timeout) as s:
            s.sendall(payload)
            return self._read(s.makefile("rb"))

    def _read(self, f):
        line = f.readline()
        if not line:
            raise RedisError("connection closed")
        kind, rest = line[:1], line[1:-2]
        if kind == b"+":
            return rest.decode()
        if kind == b"-":
            raise RedisError(rest.decode())
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            return None if n == -1 else f.read(n + 2)[:-2].decode()
        if kind == b"*":
            return [self._read(f) for _ in range(int(rest))]
        raise RedisError(f"unexpected reply {line!r}")

    def ping(self) -> bool:
        return self.command("PING") == "PONG"

    def incr(self, key: str) -> int:
        return self.command("INCR", key)
