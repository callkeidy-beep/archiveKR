FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CONTENT_MAKER_DB=/data/content-maker.sqlite3 CONTENT_MAKER_HOST=0.0.0.0 CONTENT_MAKER_PORT=3100 CONTENT_MAKER_MODE=sample CONTENT_MAKER_MAIL_DIR=/data/mail
COPY requirements.txt requirements.lock ./
COPY wheels /wheels
RUN if ls /wheels/*.whl >/dev/null 2>&1; then pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock; else pip install --no-cache-dir -r requirements.lock; fi && rm -rf /wheels && useradd --uid 10001 --create-home engine && mkdir /data && chown engine:engine /data
COPY --chown=engine:engine app ./app
COPY --chown=engine:engine web ./web
COPY --chown=engine:engine config ./config
COPY --chown=engine:engine fixtures ./fixtures
COPY --chown=engine:engine prompts ./prompts
USER engine
EXPOSE 3100
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3100/api/health',timeout=2)"
CMD ["python", "-m", "app.run"]
