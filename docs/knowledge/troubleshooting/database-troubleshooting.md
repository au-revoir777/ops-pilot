---
title: Database troubleshooting guide
doc_type: troubleshooting
services: [checkout, payments, users]
owner: sre
tags: [database, slow-query, latency]
---

# Database troubleshooting guide

## Symptoms of a database problem

- `db_query_duration_seconds` p95 rises for one or more operations, visible as
  `service_operation:db_query_seconds:p95_1m`.
- Warning logs `slow_query_detected` with `operation` and `query_time_ms`
  fields (threshold 500 ms).
- Request latency of the calling service rises by roughly the query slowdown
  multiplied by the number of queries per request.

## Is it the database or the service?

1. Compare query latency with request latency for the same service and window.
   If they rise together, the database path is the bottleneck.
2. Check whether every operation slowed down or only one. All operations
   slowing down suggests the database server itself (load, locks, storage).
   One operation slowing down suggests a query regression: a new query plan,
   a missing index, or a code change that fetches more rows.
3. Check whether a release went out shortly before the slowdown started
   (`app_info` version change). A query regression introduced by a release
   starts within minutes of the deploy and does not recover on its own.

## Safe actions

- Roll back the release if the slowdown started right after a deploy.
- Reduce load on the database (pause batch jobs) if every operation is slow.
- Capture the slow query and its plan for the postmortem.

## Unsafe actions (require human approval)

- Restarting the database, failing over, dropping or rebuilding indexes, or
  changing connection pool sizes in production.
