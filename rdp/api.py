"""FastAPI service: ingest bags and query runs, topics, messages and anomalies."""
from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .db import Anomaly, Message, Run, TopicStat, init_db, make_engine
from .ingest import IngestError, ingest_bag
from .metrics import API_REQUESTS


class IngestRequest(BaseModel):
    path: str          # relative to INGEST_ROOT
    name: str | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = init_db(engine)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="Robot Telemetry & Data Platform", version="0.1.0")

    def get_session():
        with session_factory() as session:
            yield session

    def _run_or_404(session: Session, run_id: str) -> Run:
        run = session.get(Run, run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return run

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/runs/ingest", status_code=201)
    def ingest(req: IngestRequest, session: Session = Depends(get_session)):
        root = settings.ingest_root.resolve()
        target = (root / req.path).resolve()
        if root != target and root not in target.parents:   # block path traversal
            API_REQUESTS.labels("ingest", "400").inc()
            raise HTTPException(400, "path must be inside the ingest root")
        try:
            run = ingest_bag(target, session, settings.data_dir, req.name)
        except IngestError as exc:
            API_REQUESTS.labels("ingest", "422").inc()
            raise HTTPException(422, str(exc)) from exc
        API_REQUESTS.labels("ingest", "201").inc()
        return _run_dict(run)

    @app.get("/runs")
    def list_runs(session: Session = Depends(get_session)):
        return [_run_dict(r) for r in session.scalars(select(Run).order_by(Run.start_ns.desc()))]

    @app.get("/runs/{run_id}")
    def get_run(run_id: str, session: Session = Depends(get_session)):
        return _run_dict(_run_or_404(session, run_id))

    @app.get("/runs/{run_id}/topics")
    def topics(run_id: str, session: Session = Depends(get_session)):
        _run_or_404(session, run_id)
        rows = session.scalars(select(TopicStat).where(TopicStat.run_id == run_id)
                               .order_by(TopicStat.topic))
        return [{"topic": t.topic, "msgtype": t.msgtype, "message_count": t.message_count,
                 "rate_hz": round(t.rate_hz, 3), "first_ns": t.first_ns, "last_ns": t.last_ns}
                for t in rows]

    @app.get("/runs/{run_id}/messages")
    def messages(run_id: str, topic: str, start_ns: int | None = None, end_ns: int | None = None,
                 limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                 session: Session = Depends(get_session)):
        _run_or_404(session, run_id)
        q = select(Message).where(Message.run_id == run_id, Message.topic == topic)
        if start_ns is not None:
            q = q.where(Message.stamp_ns >= start_ns)
        if end_ns is not None:
            q = q.where(Message.stamp_ns <= end_ns)
        q = q.order_by(Message.stamp_ns).limit(limit).offset(offset)
        return [{"stamp_ns": m.stamp_ns, "size_bytes": m.size_bytes, "values": m.values}
                for m in session.scalars(q)]

    @app.get("/runs/{run_id}/anomalies")
    def anomalies(run_id: str, kind: str | None = None, topic: str | None = None,
                  session: Session = Depends(get_session)):
        _run_or_404(session, run_id)
        q = select(Anomaly).where(Anomaly.run_id == run_id)
        if kind:
            q = q.where(Anomaly.kind == kind)
        if topic:
            q = q.where(Anomaly.topic == topic)
        return [{"topic": a.topic, "kind": a.kind, "severity": a.severity,
                 "start_ns": a.start_ns, "end_ns": a.end_ns, "detail": a.detail}
                for a in session.scalars(q.order_by(Anomaly.start_ns))]

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def _run_dict(run: Run) -> dict:
    return {"id": run.id, "name": run.name, "start_ns": run.start_ns, "end_ns": run.end_ns,
            "duration_s": round((run.end_ns - run.start_ns) / 1e9, 3),
            "message_count": run.message_count, "anomaly_count": run.anomaly_count}


