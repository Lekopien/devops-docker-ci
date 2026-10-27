# syntax=docker/dockerfile:1
FROM python:3.12-alpine AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Test stage: the image can't be built if the tests fail.
FROM base AS test
WORKDIR /src
COPY app ./app
COPY tests ./tests
RUN python -m unittest -v

FROM base AS runtime
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} PORT=8000
LABEL org.opencontainers.image.source="https://github.com/Lekopien/devops-docker-ci"
RUN adduser -D -u 10001 app
WORKDIR /app
COPY --from=test /src/app ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=2s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8000/healthz || exit 1
CMD ["python", "server.py"]
