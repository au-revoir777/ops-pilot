---
title: Payments service runbook
doc_type: runbook
services: [payments]
owner: payments-team
tags: [errors, declines, on-call]
---

# Payments service runbook

Payments exposes `POST /payments`, called only by checkout. It authorises and
captures a payment, then records it with the `insert_payment` query. Amounts
above 10,000.00 are declined with HTTP 402 by design; declines are business
outcomes, not errors, and do not count towards the 5xx error ratio.

## Key signals

- Error ratio: `service:http_errors:ratio_rate1m{service="payments"}`.
- Latency: `service:http_latency_seconds:p95_1m{service="payments"}`, normally under 120 ms.
- Logs: `payment_captured` (info), `payment_declined` (info, reason field),
  `request_processing_failed` (error).

## Payments returning 5xx

1. Confirm the error ratio and the start time.
2. Check whether checkout errors started at the same time. Checkout turns
   payments 5xx into its own 502 responses (`dependency_error` logs with
   `target=payments`), so a payments problem usually shows up first as a
   checkout alert.
3. Check the deployed payments version and recent changes.
4. If payments latency is also high, check its database query latency.

## Spike in declines

A rise in `payment_declined` without 5xx is usually a client or pricing change
(very large carts), not an outage. Compare the decline reason field with recent
checkout releases before paging the payments team.
