# ---- build the web app ------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- API + static hosting ---------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    MONEY_DB=/data/money.db MONEY_CACHE_DIR=/data/cache
COPY backend/ ./backend/
# Editable install: the API serves the SPA from /app/frontend/dist (next to backend/).
RUN pip install --no-cache-dir -e ./backend
COPY --from=web /app/frontend/dist ./frontend/dist
VOLUME ["/data"]
EXPOSE 8000
# Hosts such as Render, Railway and Fly inject $PORT; default to 8000 elsewhere.
CMD ["sh", "-c", "exec uvicorn money.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
