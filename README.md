# DevOps: Docker, Compose and CI/CD

[![ci](https://github.com/Lekopien/devops-docker-ci/actions/workflows/ci.yml/badge.svg)](https://github.com/Lekopien/devops-docker-ci/actions/workflows/ci.yml)

**Project page: https://devops.lekopien.com**

A small service packaged the way production services are: a hardened multi-stage Docker image, an **nginx load balancer** in front of **three replicas**, **Redis** for shared state, health and readiness probes, Prometheus metrics, structured JSON logs, graceful shutdown, and a **GitHub Actions pipeline** that tests, lints, spins up the whole stack, smoke-tests it and publishes the image to GitHub Container Registry. Everything runs on free tiers.

```
            ┌──────────── docker compose ─────────────┐
 :8080 ──►  │  nginx ──round-robin──► app ×3 ──► redis │
            │  rate limit, gzip,      /healthz  (AOF   │
            │  security headers       /readyz    volume)│
            │                         /metrics          │
            └───────────────────────────────────────────┘
```

## Run it

```bash
make up          # docker compose up -d --build --wait
make smoke       # health, readiness, load balancing, rate limiting
make scale N=5   # more replicas, nginx picks them up via DNS
make logs
make down
make test        # unit tests without Docker
```

Open http://localhost:8080 and refresh: the page shows which replica answered while the visit counter (in Redis) keeps counting across all of them.

## What it demonstrates

| Practice | Where |
| --- | --- |
| Multi-stage build where **tests run inside the build**: no image if they fail | `Dockerfile` |
| Non-root user, read-only filesystem, `no-new-privileges`, CPU and memory limits | `Dockerfile`, `compose.yaml` |
| Container `HEALTHCHECK`, `depends_on: service_healthy`, `up --wait` | `Dockerfile`, `compose.yaml` |
| Liveness (`/healthz`) vs readiness (`/readyz` checks Redis) | `app/server.py` |
| Graceful degradation: counter falls back to memory if Redis is down | `app/server.py` |
| Prometheus counters and latency histogram at `/metrics`, blocked at the edge | `app/server.py`, `nginx/nginx.conf` |
| Reverse proxy: round-robin, keepalive, retries, per-IP rate limiting, gzip, security headers, JSON access logs | `nginx/nginx.conf` |
| Graceful shutdown on `SIGTERM` | `app/server.py` |
| Redis RESP protocol client in ~50 lines, no dependencies | `app/redis_client.py` |
| CI: unit tests, Dockerfile lint (hadolint), full-stack integration and smoke test, publish to GHCR on `main` | `.github/workflows/ci.yml` |
| Automated dependency updates for base images and actions | `.github/dependabot.yml` |

## CI/CD pipeline

```
push / PR ──► test (unittest + hadolint) ──► integration (compose up + smoke.sh) ──► publish (main only → ghcr.io)
```

Pull the published image:

```bash
docker run -p 8000:8000 ghcr.io/lekopien/devops-docker-ci:latest
```

## License

MIT
