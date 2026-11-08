---
title: Checkout architecture
doc_type: architecture
services: [checkout, users, payments]
owner: commerce-platform
tags: [architecture, dependencies]
---

# Checkout architecture

## Request flow

`POST /checkout` (port 8080) runs these steps sequentially, so their latencies add up:

1. `GET users:/users/{user_id}`: user lookup (typically 10 to 30 ms).
   An unknown user ends the request with 422 before any payment.
2. Database query `select_cart_items`: loads prices for the cart (15 to 50 ms).
3. `POST payments:/payments`: authorise and capture (40 to 90 ms).
   A decline (402) is passed through to the client.
4. Database query `insert_order`: persists the order (5 to 20 ms).

Because the two database queries sit on the critical path of every request, a
slow database shows up almost one-to-one in checkout request latency: if each
query gains about 900 ms, checkout p95 rises from roughly 200 ms to roughly 2 s.

## Failure handling

- Dependency 5xx: checkout returns 502 `DEPENDENCY_ERROR`.
- Dependency timeout (5 s): 504 `DEPENDENCY_TIMEOUT`.
- Dependency unreachable: 502 `DEPENDENCY_UNAVAILABLE`.
- Every call forwards the `X-Request-ID` header, so one request can be traced
  across checkout, users and payments in the logs.

## Deployment

Checkout runs as its own container. The deployed version is exported as
`app_info{service="checkout",version=...}` and appears on every log line.
