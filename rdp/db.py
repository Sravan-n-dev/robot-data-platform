"""SQLAlchemy models and engine helpers."""
from __future__ import annotations

from sqlalchemy import (JSON, BigInteger, Float, ForeignKey, Index, Integer,
                        String, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    source_path: Mapped[str] = mapped_column(String(1024))
    start_ns: Mapped[int] = mapped_column(BigInteger)
    end_ns: Mapped[int] = mapped_column(BigInteger)
    message_count: Mapped[int] = mapped_column(Integer)
    anomaly_count: Mapped[int] = mapped_column(Integer, default=0)


class TopicStat(Base):
    __tablename__ = "topic_stats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(255))
    msgtype: Mapped[str] = mapped_column(String(255))
    message_count: Mapped[int] = mapped_column(Integer)
    rate_hz: Mapped[float] = mapped_column(Float)
    first_ns: Mapped[int] = mapped_column(BigInteger)
    last_ns: Mapped[int] = mapped_column(BigInteger)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(String(255))
    stamp_ns: Mapped[int] = mapped_column(BigInteger)
    size_bytes: Mapped[int] = mapped_column(Integer)
    values: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (Index("ix_messages_run_topic_stamp", "run_id", "topic", "stamp_ns"),)


class Anomaly(Base):
    __tablename__ = "anomalies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    topic: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    start_ns: Mapped[int] = mapped_column(BigInteger)
    end_ns: Mapped[int] = mapped_column(BigInteger)
    detail: Mapped[str] = mapped_column(String(512))


def make_engine(url: str):
    """Create an engine; SQLite gets thread-safe settings for the API and tests."""
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


def init_db(engine) -> sessionmaker:
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
