import os
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel

app = FastAPI(title="Deployment demo catalogue")
RELEASE = Path(__file__).with_name("release.txt").read_text().strip()


class Item(BaseModel):
    id: int
    name: str


def connect():
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        connect_timeout=3,
        options="-c statement_timeout=3000 -c default_transaction_read_only=on",
        row_factory=dict_row,
    )


def query(statement):
    try:
        with connect() as connection:
            return connection.execute(statement).fetchall()
    except psycopg.Error:
        raise HTTPException(status_code=503, detail="Catalogue unavailable") from None


@app.get("/health/live")
def live():
    return {"status": "alive"}


@app.get("/health/ready")
def ready():
    query("SELECT id, name FROM public.items LIMIT 1")
    return {"status": "ready"}


@app.get("/version")
def version():
    return {"release": RELEASE}


@app.get("/items", response_model=list[Item])
def items():
    return query("SELECT id, name FROM public.items ORDER BY id LIMIT 100")
