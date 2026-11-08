---
title: Checkout service runbook
doc_type: runbook
services: [checkout]
owner: commerce-platform
tags: [latency, errors, on-call]
---

# Checkout service runbook

Checkout handles `POST /checkout`. One request does four things in order:
looks up the user in the users service, reads cart items from the database
(`select_cart_items`), charges the payments service, and writes the order
(`insert_order`). Normal p95 latency is about 200 ms; p99 stays under 400 ms.

## Key signals

- Latency: `service:http_latency_seconds:p95_1m{service="checkout"}`.
- Error ratio: `service:http_errors:ratio_rate1m{service="checkout"}` (5xx only).
- Database: `service_operation:db_query_seconds:p95_1m{service="checkout"}` per operation.
- Dependencies: `downstream_request_duration_seconds_count{service="checkout"}` by `target` and `outcome`.
- Version: `app_info{service="checkout"}` shows what is deployed right now.
- Logs: `request_slow` (warning), `slow_query_detected` (warning),
  `dependency_error`, `dependency_timeout`, `dependency_unreachable` (error).

## Alert: HighLatencyP95 on checkout

1. Confirm the alert in Grafana ("OpsPilot — Services", latency panel). Check
   whether p50 moved too or only the tail.
2. Check whether the deployed version changed in the last hour (`app_info`).
   A latency step that starts minutes after a deploy points at the release.
3. Split the time: compare checkout p95 with users and payments p95. If the
   dependencies are healthy, the time is spent inside checkout.
4. Look at database query latency per operation. If `select_cart_items` or
   `insert_order` p95 rose together with request latency and the logs show
   `slow_query_detected`, follow the database troubleshooting guide.
5. If only request latency rose and the database and dependencies are flat,
   suspect CPU starvation or a code path regression in checkout itself.

## Alert: HighErrorRate on checkout

1. Read the error logs for checkout in the alert window.
2. `dependency_error` with `target=payments` means payments is returning 5xx:
   checkout reports these as 502. Investigate payments first.
3. `dependency_timeout` means a dependency did not answer within the client
   timeout (5 s); checkout returns 504.
4. `request_processing_failed` with no dependency errors points at checkout
   itself. Correlate with the deployed version.

## Mitigation

- Release regression: roll back to the previous version (see the deployment
  rollback procedure). Rolling back is preferred over hot-fixing during an incident.
- Dependency outage: checkout cannot complete orders without payments; communicate
  impact, do not retry aggressively (it amplifies load on payments).
- Never restart database instances or delete data as a first response.
