# ---------- Stage 1: Build React UI ----------
FROM node:24-alpine AS ui-builder

WORKDIR /ui

COPY ui/package*.json ./
RUN npm ci

COPY ui/ ./
RUN npm run build


# ---------- Stage 2: Python application ----------
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/api

# Python dependencies
COPY api/requirements.txt ./api/requirements.txt

RUN pip install --no-cache-dir -r api/requirements.txt

# Application code
COPY api/ ./api/

# Copy built React application
COPY --from=ui-builder /ui/dist ./ui/dist

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "/app/api", "--host", "0.0.0.0", "--port", "8000"]