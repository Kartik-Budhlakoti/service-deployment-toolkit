FROM python:3.14-slim@sha256:af8a5aa14780025dbfbcfbc81bd8a91ebd87711dd5b0f48ed71090949dd7cb1d

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.lock .
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip --no-cache-dir check \
    && groupadd --gid 10001 demo \
    && useradd --uid 10001 --gid demo --no-create-home demo

COPY app/ ./app/
COPY db/ ./db/

USER 10001:10001

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
