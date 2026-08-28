# MOSAIC observability runbook

This slice adds application-owned JSON logs, low-cardinality Prometheus text
metrics, dependency readiness gauges, alerts and dashboard queries. It does
not replace PostgreSQL ledger data, RabbitMQ state, reconciliation records or
the release/backup gates.

## Endpoints and configuration

The API exposes metrics only at `GET /internal/metrics`, outside the public
`/api/v1` contract and excluded from OpenAPI. Set `METRICS_ENABLED=false` to
disable it. When `METRICS_INTERNAL_TOKEN` is non-empty, use either the
`X-Mosaic-Metrics-Token` header or `Authorization: Bearer ...`; unauthorized
requests return 404 and the supplied token is never logged.

In the production-shaped Compose profile:

- API metrics are reachable only on the Compose network at `api:8000/internal/metrics`.
- relay/worker processes can expose the same path on their internal listener at
  port `9090` when `MOSAIC_WORKER_METRICS_ENABLED=true`.
- worker listener binding is `MOSAIC_METRICS_BIND_HOST=0.0.0.0` inside the
  container; `expose`, not `ports`, is used for 9090.
- the API service has no host `ports` mapping. Only the Web service has a host
  port in `docker-compose.production.yml`.

Prometheus must therefore run on the same private network or through an
operator-controlled internal route. Example target paths are:

```yaml
scrape_configs:
  - job_name: mosaic-api
    metrics_path: /internal/metrics
    static_configs:
      - targets: [api:8000]
    authorization:
      type: Bearer
      credentials_file: /run/secrets/mosaic_metrics_token
  - job_name: mosaic-workers
    metrics_path: /internal/metrics
    static_configs:
      - targets: [chat-relay:9090, generation-relay:9090, chat-worker:9090, image-audio-worker:9090, video-worker:9090]
    authorization:
      type: Bearer
      credentials_file: /run/secrets/mosaic_metrics_token
```

The example is an operator configuration, not a checked-in secret. Scrape
every process because counters and gauges are process-local.

## Readiness and dependencies

`/api/v1/health/live` is a process liveness check and must not probe external
dependencies. `/api/v1/health/ready` is the traffic gate and remains a stable
public contract. Its dependency breakdown is available in metrics:
`database`, `redis`, `provider`, `chat_worker`, `chat_relay`,
`generation_worker`, `generation_relay`, and the two stack aggregates. A zero
means that dependency is not ready; do not route traffic while a required
dependency is zero.

If live is healthy but ready is not, inspect the first zero dependency and
then its own service logs. Do not print connection URLs, credentials, cookies,
request bodies or provider responses while diagnosing the failure.

## HTTP errors and latency

Start with the 5xx ratio, P95 latency and `status_code`/normalized `route`
breakdowns from `infra/observability/dashboard-queries.md`. Correlate a single
customer report with the response `X-Request-ID` and the JSON log `request_id`.
The request middleware records method, normalized route, status and duration;
it never records query strings, headers, cookies or bodies.

## Database pool

Check `mosaic_db_pool_checked_out`, `mosaic_db_pool_size`, checked-in and
overflow gauges. Sustained utilization above 80% can indicate slow queries,
an unavailable dependency or insufficient pool sizing. Preserve the database
and RLS boundaries; do not “fix” pool pressure by bypassing tenant policies or
changing the application database role.

## Outbox and workers

Inspect outbox claimed/published/retry/fenced counters by bounded event type,
then inspect RabbitMQ quorum queue health and the relay readiness heartbeat.
Fenced marks indicate lease ownership changed; preserve the row and its
lineage instead of manually marking it published.

Worker success/failure counters are split by `chat`, `generation_media` and
`generation_video`. `submitted_unknown` is not an ordinary failure: stop blind
retries, retain the billing hold, and follow the existing provider/operator
reconciliation procedure. Never use a prompt, job ID or provider request body
as a metric label.

## Redis permits and SSE

Permit saturation is capacity pressure, while permit loss means a renewal or
release could not be confirmed. Check Redis health, worker lease heartbeats and
the bounded `resource` breakdown. A Redis stream notification loss is repaired
by database replay; inspect the SSE replay-fallback reason and active
connection gauge. Do not increase limits before checking Redis latency and
tenant-safe capacity.

## Billing and artifacts

Billing hold/capture/release counters describe observed domain operations;
PostgreSQL reservations and the append-only ledger remain authoritative. Any
billing invariant alert is a page: preserve the database state, stop unsafe
manual edits, and use the existing reconciliation/audit path.

Artifact byte counters use only `read`/`write` direction. Transfer failures
are grouped by bounded operation (`open_stream`, `put_bytes`, or
`transfer_remote`). Check object-store health, MIME/size policy and the job's
durable artifact status; do not log signed URLs, object bodies or credentials.

## Log safety and restart behavior

Application JSON logs always contain `request_id`, `service`, `version`,
`level` and `event`. The formatter allowlists operational scalar fields and
does not serialize arbitrary log messages or exceptions, so cookies, passwords,
tokens, provider URLs and bodies are excluded by construction.

Metrics are in-process and reset on restart. A scrape gap or process restart
is not evidence that counters were zero; alert on rates and readiness, and
verify scrape health separately. This slice does not claim tracing, durable
cross-process aggregation, load/chaos validation, or backup/restore proof.
