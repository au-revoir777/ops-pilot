---
title: "Postmortem: checkout latency from a cart query regression (simulated)"
doc_type: postmortem
services: [checkout]
owner: commerce-platform
tags: [postmortem, slow-query, rollback, simulated]
incident_date: 2026-09-14
---

# Postmortem: checkout latency from a cart query regression

This is a simulated postmortem written for the OpsPilot demo knowledge base.

## Summary

After checkout version 1.7.4 was deployed, checkout p95 latency rose from about
200 ms to about 2.3 s for 41 minutes. No requests failed, but conversion
dropped. Rolling back to 1.7.3 restored normal latency.

## Timeline

- 10:02 checkout 1.7.4 deployed.
- 10:05 p95 latency starts climbing; `HighLatencyP95` fires at 10:07.
- 10:15 on-call sees users and payments latency flat, so the time is inside checkout.
- 10:24 `slow_query_detected` warnings found for `select_cart_items`
  (query_time_ms around 1,900).
- 10:38 decision to roll back; 10:43 rollback to 1.7.3 complete; latency normal at 10:46.

## Root cause

Release 1.7.4 changed the cart query to join an additional table without an
index, turning an index lookup into a sequential scan on large carts.

## What went well / what did not

- Went well: the dependency map quickly ruled out users and payments.
- Did not: it took 20 minutes to connect the latency step to the deploy;
  the deploy time was not visible next to the latency graph.

## Action items

- Show deployed versions next to latency on the service dashboard.
- Add a query-plan check for cart queries to CI.
- Prefer rollback first when a latency step follows a deploy within minutes.
