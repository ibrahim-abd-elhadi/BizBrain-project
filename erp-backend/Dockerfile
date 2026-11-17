FROM python:3.12.16-slim

WORKDIR /app

COPY pyproject.toml alembic.ini docker-entrypoint.sh ./
COPY src ./src
COPY migrations ./migrations

RUN pip install --no-cache-dir . && chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
