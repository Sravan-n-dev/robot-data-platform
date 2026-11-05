# Robot Telemetry & Data Platform

![CI](https://github.com/Sravan-n-dev/robot-data-platform/actions/workflows/ci.yml/badge.svg)

A small data platform for robot logs. It ingests ROS 2 bag files, stores them in
PostgreSQL (queryable summaries) and Parquet (columnar features for analytics),
runs automated data-quality checks, and exposes everything through a FastAPI
service with Prometheus metrics and a Grafana dashboard.

The goal: when a robot run comes back from the field, you can answer *"what data
did we get, and is it any good?"* without opening the bag by hand.

## Architecture

```
 ROS 2 bag (.db3 / .mcap)
        |
   rosbags reader  ->  feature extractors (Odometry, LaserScan, Imu, Twist)
        |                         |
        |                 anomaly detection (gaps, dropouts, bad timestamps, NaN)
        v                         v
  Parquet per topic        PostgreSQL: runs, topic_stats, messages, anomalies
        \________________________/
                    |
              FastAPI service  ---->  /metrics  ->  Prometheus  ->  Grafana
```

## Quick start

Local (SQLite, no ROS install needed):

```bash
pip install -r requirements.txt
python scripts/generate_sample_bag.py --out bags/sample_run     # synthetic bag with injected faults
uvicorn rdp.api:create_app --factory --port 8000
curl -X POST localhost:8000/runs/ingest -H 'content-type: application/json' -d '{"path":"sample_run"}'
```

Full stack (PostgreSQL + API + Prometheus + Grafana):

```bash
docker compose up --build
# API: http://localhost:8000/docs   Prometheus: :9090   Grafana: :3000 (admin/admin)
```

Put your own bags in `./bags/`; the API only ingests paths inside that folder.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/runs/ingest` | Ingest a bag by path (relative to `INGEST_ROOT`) |
| GET | `/runs`, `/runs/{id}` | List runs / run summary |
| GET | `/runs/{id}/topics` | Per-topic message count, measured rate, time span |
| GET | `/runs/{id}/messages?topic=&start_ns=&end_ns=` | Time-range query with pagination |
| GET | `/runs/{id}/anomalies?kind=&topic=` | Data-quality findings |
| GET | `/metrics` | Prometheus metrics |

## Data-quality checks

| Kind | Meaning | How it is detected |
|---|---|---|
| `message_drop` | A few messages missing | Log-time gap > 1.8x the topic's median period |
| `sensor_dropout` | Sensor went silent | Gap >= 10x the median period and >= 0.5 s |
| `timestamp_regression` / `timestamp_duplicate` | Bad header stamps | Header time moves backwards or repeats |
| `invalid_values` | NaN/inf in required fields | Per-message finite check on decoded features |

The median period is used as the nominal rate because it stays accurate even when
large gaps exist.

## Verified behaviour

The synthetic bag (30 s, `/odom` 20 Hz, `/scan` 10 Hz, `/imu` 50 Hz) injects four
faults. The pipeline ingests it (2,364 messages) and reports exactly those four:

```
/odom invalid_values       warning   1 message(s) contained NaN/inf in required fields
/odom message_drop         warning   about 6 message(s) missing; gap 0.350s
/scan sensor_dropout       critical  no data for 3.10s (nominal period 0.100s)
/imu  timestamp_regression critical  header stamp moved backwards by 0.480s
```

A fault-free bag produces zero anomalies. Run `pytest -q` (12 tests: detectors, ingest,
Parquet output, time-range queries, path-traversal protection, metrics).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./rdp.db` | SQLAlchemy URL (PostgreSQL in compose) |
| `DATA_DIR` | `./data` | Where Parquet files are written |
| `INGEST_ROOT` | `./bags` | Only bags under this folder can be ingested |

## Limitations

- Only Odometry, LaserScan, Imu and Twist are decoded in detail; other topics are
  ingested for timing and size only. Add a function to `rdp/extractors.py` to support more.
- Camera images and point clouds are not stored, only their timing.
- Whole bags are read into memory before writing, so very large bags need streaming/chunking.
- Ingestion is synchronous. A job queue (for example my ScaleForge project) would be the next step.
- The Grafana dashboard shows ingestion and data-quality metrics of the platform, not live robot telemetry.
- Tested with the synthetic bag; try it on real robot bags and open issues for any message types that fail.

## Project layout

```
rdp/          ingest, extractors, anomaly detection, API, DB models, metrics
scripts/      synthetic bag generator
tests/        pytest suite
monitoring/   Prometheus config and Grafana provisioning
```
