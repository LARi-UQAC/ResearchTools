# form-service. No AGPL dependency ships in this image.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SKILL_SCRIPTS_DIR=/opt/form-service/scripts \
    SCOPUS_SCRIPTS_DIR=/opt/scopus/scripts

WORKDIR /srv

COPY deploy/form-service/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt

# The skill is the library; the service is the transport. RT-6's
# GET /publications imports scopus_api.py from a second skill.
COPY .claude/skills/form-service/scripts /opt/form-service/scripts
COPY .claude/skills/scopus/scripts /opt/scopus/scripts
COPY deploy/form-service/app /srv/app

# Non-root. Two data directories: the signing certificate and the
# publications cache, neither of which holds a request body.
RUN useradd --system --create-home --uid 10001 formsvc \
    && mkdir -p /data/certs /data/publications \
    && chown -R formsvc:formsvc /data /srv
USER formsvc

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4).status==200 else 1)"

# Inside the container the process binds 0.0.0.0 because it is reachable only on
# the compose network behind Caddy, and the published port is bound to 127.0.0.1
# on the host. A local run outside Docker binds 127.0.0.1 (see README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
