"""Lazy MySQL connection setup; importing the API never opens a connection."""
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    pass


class DatabaseConfigurationError(Exception):
    pass


def database_url() -> URL:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    required = ("MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD")
    if any(not os.getenv(name) for name in required):
        raise DatabaseConfigurationError("请配置 MYSQL_DATABASE、MYSQL_USER、MYSQL_PASSWORD。")
    try:
        port = int(os.getenv("MYSQL_PORT", "3306"))
        if not 1 <= port <= 65535:
            raise ValueError
    except ValueError as exc:
        raise DatabaseConfigurationError("MYSQL_PORT 必须是有效端口。") from exc
    return URL.create(
        "mysql+pymysql", username=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        host=os.getenv("MYSQL_HOST", "127.0.0.1"), port=port,
        database=os.environ["MYSQL_DATABASE"], query={"charset": "utf8mb4"},
    )


@lru_cache(maxsize=1)
def get_engine():
    return create_engine(database_url(), pool_pre_ping=True, pool_recycle=1800,
                         connect_args={"connect_timeout": 5, "read_timeout": 15, "write_timeout": 15})


def get_db():
    with Session(get_engine(), expire_on_commit=False) as db:
        yield db
