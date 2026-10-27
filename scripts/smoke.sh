#!/usr/bin/env sh
# Smoke test for the running stack: health, readiness, load balancing and rate limiting.
set -eu
BASE=${BASE:-http://localhost:8080}

echo "health:    $(curl -fsS "$BASE/healthz")"
echo "readiness: $(curl -fsS "$BASE/readyz")"

instances=$(for i in $(seq 1 12); do curl -fsS "$BASE/api/hits" | sed 's/.*"instance": "\([^"]*\)".*/\1/'; done | sort -u | wc -l)
echo "replicas answering: $instances"
[ "$instances" -ge 2 ] || { echo "expected load balancing across replicas"; exit 1; }

code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/metrics")
echo "/metrics from outside: $code"
[ "$code" = 403 ] || { echo "metrics should not be public"; exit 1; }

limited=$(for i in $(seq 1 60); do curl -s -o /dev/null -w '%{http_code}\n' "$BASE/healthz"; done | grep -c 429 || true)
echo "rate-limited responses in a burst of 60: $limited"
[ "$limited" -gt 0 ] || { echo "expected rate limiting"; exit 1; }
echo "smoke test passed"
