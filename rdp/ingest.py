"""Read a ROS 2 bag, store summaries in SQL and full features in Parquet."""
from __future__ import annotations

import re
import time
import uuid
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from rosbags.highlevel import AnyReader
from sqlalchemy.orm import Session

from . import anomaly
from .db import Anomaly, Message, Run, TopicStat
from .extractors import extract, is_valid
from .metrics import ANOMALIES, INGEST_SECONDS, MESSAGES, RUNS


class IngestError(Exception):
    """Raised when a bag cannot be read or is empty."""


def _safe(topic: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", topic.strip("/")) or "root"


def ingest_bag(bag_path: Path, session: Session, data_dir: Path, name: str | None = None) -> Run:
    """Ingest one bag directory (or .mcap file). Returns the stored Run."""
    bag_path = Path(bag_path)
    if not bag_path.exists():
        raise IngestError(f"bag not found: {bag_path}")
    started = time.perf_counter()

    stamps: dict[str, list[int]] = defaultdict(list)
    sizes: dict[str, list[int]] = defaultdict(list)
    feats: dict[str, list[dict]] = defaultdict(list)
    types: dict[str, str] = {}
    try:
        with AnyReader([bag_path]) as reader:
            for conn, stamp, raw in reader.messages():
                msg = reader.deserialize(raw, conn.msgtype)
                types[conn.topic] = conn.msgtype
                stamps[conn.topic].append(int(stamp))
                sizes[conn.topic].append(len(raw))
                feats[conn.topic].append(extract(conn.msgtype, msg))
    except Exception as exc:  # corrupted or unsupported bag
        raise IngestError(f"could not read bag {bag_path}: {exc}") from exc
    if not stamps:
        raise IngestError(f"bag contains no messages: {bag_path}")

    run_id = str(uuid.uuid4())
    all_first = min(s[0] for s in stamps.values())
    all_last = max(s[-1] for s in stamps.values())
    total = sum(len(s) for s in stamps.values())
    run = Run(id=run_id, name=name or bag_path.name, source_path=str(bag_path),
              start_ns=all_first, end_ns=all_last, message_count=total, anomaly_count=0)
    session.add(run)
    session.flush()

    run_dir = Path(data_dir) / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    findings_total = 0

    for topic, ts_list in stamps.items():
        ts = np.asarray(ts_list, dtype=np.int64)
        msgtype = types[topic]
        values = feats[topic]
        span_s = (ts[-1] - ts[0]) / 1e9
        rate = (len(ts) - 1) / span_s if span_s > 0 else 0.0
        session.add(TopicStat(run_id=run_id, topic=topic, msgtype=msgtype,
                              message_count=len(ts), rate_hz=float(rate),
                              first_ns=int(ts[0]), last_ns=int(ts[-1])))
        session.bulk_insert_mappings(Message, [
            {"run_id": run_id, "topic": topic, "stamp_ns": int(t), "size_bytes": int(sz), "values": v}
            for t, sz, v in zip(ts_list, sizes[topic], values)])

        # Parquet: one file per topic with columnar features for analytics.
        columns: dict[str, list] = {"stamp_ns": ts_list, "size_bytes": sizes[topic]}
        for key in sorted({k for v in values for k in v}):
            columns[key] = [v.get(key) for v in values]
        pq.write_table(pa.table(columns), run_dir / f"{_safe(topic)}.parquet")

        findings = anomaly.detect_gaps(ts)
        headers = [v["header_ns"] for v in values if "header_ns" in v]
        if len(headers) == len(values):
            findings += anomaly.detect_timestamp_issues(np.asarray(headers, dtype=np.int64))
        valid = np.asarray([is_valid(msgtype, v) for v in values], dtype=bool)
        findings += anomaly.detect_invalid(ts, valid)
        for f in findings:
            session.add(Anomaly(run_id=run_id, topic=topic, kind=f.kind, severity=f.severity,
                                start_ns=f.start_ns, end_ns=f.end_ns, detail=f.detail))
            ANOMALIES.labels(kind=f.kind).inc()
        findings_total += len(findings)

    run.anomaly_count = findings_total
    session.commit()
    RUNS.inc()
    MESSAGES.inc(total)
    INGEST_SECONDS.observe(time.perf_counter() - started)
    return run
