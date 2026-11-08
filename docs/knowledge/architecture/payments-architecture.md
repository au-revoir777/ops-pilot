---
title: Payments architecture
doc_type: architecture
services: [payments]
owner: payments-team
tags: [architecture]
---

# Payments architecture

Payments (port 8081) is an internal service. Its only client is checkout.

## Request flow

1. Validate the request (order id, user id, positive amount in cents).
2. Call the card network (simulated; 20 to 50 ms).
3. Apply the decline rule: amounts above 10,000.00 return 402 `PAYMENT_DECLINED`.
4. Record the payment with the `insert_payment` query.
5. Return 201 with a `payment_id` and status `captured`.

## Dependencies and blast radius

Payments has no downstream service dependencies, only its database. When
payments fails, checkout cannot complete orders: checkout availability can never
be better than payments availability. Users is unaffected by payments outages.

## Observability

Same metric names as every OpsPilot-monitored service:
`http_requests_total`, `http_request_duration_seconds`,
`http_request_errors_total`, `db_query_duration_seconds{operation="insert_payment"}`,
and `app_info` for the deployed version.
