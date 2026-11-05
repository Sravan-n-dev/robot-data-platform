"""Prometheus metrics exposed at /metrics."""
from prometheus_client import Counter, Histogram

RUNS = Counter("rdp_runs_ingested_total", "Bag files ingested")
MESSAGES = Counter("rdp_messages_ingested_total", "Messages ingested")
ANOMALIES = Counter("rdp_anomalies_detected_total", "Data-quality anomalies found", ["kind"])
INGEST_SECONDS = Histogram("rdp_ingest_duration_seconds", "Time to ingest one bag")
API_REQUESTS = Counter("rdp_api_requests_total", "API requests", ["endpoint", "status"])
