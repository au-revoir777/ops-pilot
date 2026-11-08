---
title: Service dependency map
doc_type: architecture
services: [checkout, payments, users, opspilot-api]
owner: sre
tags: [dependencies, blast-radius]
---

# Service dependency map

| Service | Calls | Called by | Datastore |
|---|---|---|---|
| checkout | users, payments | clients | orders/cart database |
| payments | none | checkout | payments database |
| users | none | checkout | users database |
| opspilot-api | none (reads telemetry later via MCP) | operators, UI | PostgreSQL + pgvector |

## Reading the map during an incident

- A problem in users or payments surfaces as checkout errors or latency, because
  checkout calls both synchronously on every request.
- A problem confined to checkout leaves users and payments metrics flat. If
  checkout latency rises while both dependencies stay at their normal p95, the
  time is being spent inside checkout: its own code or its database queries.
- Users and payments do not call each other, so an outage in one does not
  affect the other.

## Ports

checkout 8080, payments 8081, users 8082, opspilot-api 8000. All services expose
`/health` (liveness) and `/metrics` (Prometheus).
