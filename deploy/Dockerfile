FROM postgres:17-bookworm@sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27 AS pgtools
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates gnupg libpq5 liblz4-1 libzstd1 libreadline8 \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip install --no-cache-dir uv==0.12.23
# Same Debian release and target architecture; copy official PostgreSQL 17 clients.
COPY --from=pgtools /usr/lib/postgresql/17/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=pgtools /usr/lib/postgresql/17/bin/pg_restore /usr/local/bin/pg_restore
COPY --from=pgtools /usr/lib/postgresql/17/bin/psql /usr/local/bin/psql
COPY --from=pgtools /usr/lib/*/libpq.so.5* /usr/local/lib/
RUN ldconfig && pg_dump --version && pg_restore --version
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
RUN DJANGO_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(64))') APP_ENV=production DJANGO_DEBUG=0 python manage.py collectstatic --noinput \
 && groupadd --gid 10001 garrafas && useradd --uid 10001 --gid 10001 --create-home garrafas \
 && mkdir -p /backups && chown 10001:10001 /backups && chmod 0700 /backups
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "90", "--access-logfile", "-", "--access-logformat", "%(m)s %(U)s %(s)s %(L)s"]
