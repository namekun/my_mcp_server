# ---- base ----
FROM python:3.11-slim AS base

# 안전한 기본 패키지 (인증서/로케일 최소)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tini && \
    rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# ---- deps ----
FROM base AS deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---- runtime ----
FROM base AS runtime
# 비루트 권장
RUN useradd -m appuser
USER appuser

WORKDIR /app
# 의존성 레이어 복사
COPY --from=deps /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=deps /usr/local/bin /usr/local/bin

# 앱 소스 복사
COPY . /app

# 로깅 레벨 (필요시 docker run 환경변수로 덮어쓰기)
ENV LOG_LEVEL=INFO

# STDIO 유지에 유용한 tini 사용
ENTRYPOINT ["/usr/bin/tini", "--"]

# STDIO 기반 MCP 서버 실행
CMD ["python", "server.py"]