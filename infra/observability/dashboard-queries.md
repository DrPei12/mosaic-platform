# MOSAIC observability dashboard queries

All labels below are bounded route/status/event/worker/resource values. Do not
add tenant, job, request, provider URL, prompt, token or other user-controlled
values to a dashboard grouping.

| Panel | PromQL |
| --- | --- |
| Request rate | `sum(rate(mosaic_http_requests_total[5m]))` |
| 5xx ratio | `sum(rate(mosaic_http_requests_total{status_code=~"5.."}[5m])) / clamp_min(sum(rate(mosaic_http_requests_total[5m])), 1)` |
| P95 request latency | `histogram_quantile(0.95, sum by (le) (rate(mosaic_http_request_duration_seconds_bucket[5m])))` |
| P95 latency by route | `histogram_quantile(0.95, sum by (route, le) (rate(mosaic_http_request_duration_seconds_bucket[5m])))` |
| Dependency readiness | `mosaic_dependency_ready` |
| DB pool utilization | `mosaic_db_pool_checked_out / clamp_min(mosaic_db_pool_size, 1)` |
| Outbox throughput | `sum by (event_type) (rate(mosaic_outbox_published_total[5m]))` |
| Outbox retries/fences | `sum by (event_type) (rate(mosaic_outbox_retry_total[5m]))` and `sum by (event_type) (rate(mosaic_outbox_fenced_total[5m]))` |
| Worker outcomes | `sum by (worker) (rate(mosaic_worker_success_total[5m]))`, with failure and submitted-unknown counterparts |
| Redis permit pressure | `sum by (resource) (rate(mosaic_redis_permit_saturation_total[5m]))` |
| Redis permit loss | `sum by (resource) (rate(mosaic_redis_permit_loss_total[5m]))` |
| Active SSE | `mosaic_sse_active_connections` |
| SSE replay fallback | `sum by (reason) (rate(mosaic_sse_replay_fallback_total[5m]))` |
| Billing operations | `rate(mosaic_billing_hold_total[5m])`, `rate(mosaic_billing_capture_total[5m])`, `rate(mosaic_billing_release_total[5m])` |
| Billing invariants | `sum by (invariant) (increase(mosaic_billing_invariant_total[1h]))` |
| Artifact bytes | `sum by (direction) (rate(mosaic_artifact_transfer_bytes_total[5m]))` |
| Artifact failures | `sum by (direction, operation) (rate(mosaic_artifact_transfer_failures_total[5m]))` |

Counters reset when a process restarts. Use `rate`/`increase`, and scrape the
API plus every relay/worker target rather than treating the API process as a
global counter store.
