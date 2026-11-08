---
title: Latency troubleshooting guide
doc_type: troubleshooting
services: [checkout, payments, users]
owner: sre
tags: [latency, p95, investigation]
---

# Latency troubleshooting guide

Use this guide when a service's p95 or p99 latency increases.

## 1. Characterise the change

- When did it start? Find the first minute where p95 left its normal band.
- Is it a step (sudden, sustained) or a ramp (gradual)? Steps usually come from
  a deploy, a configuration change or a dependency failure; ramps from growing
  load, leaks or data growth.
- Did traffic change? Compare `service:http_requests:rate1m` before and after.
- Did errors change? Latency with rising 5xx often means timeouts.

## 2. Locate the time

- Compare the slow service with its dependencies (see the service dependency map).
- Check per-route latency: a single slow route narrows the search.
- Check database query latency per operation and downstream call latency.
- Read `request_slow` warnings (logged above 1 s) and any `slow_query_detected`
  warnings in the same window; follow one slow request across services using its
  `request_id`.

## 3. Correlate with changes

- Deployed version changes (`app_info`) in the hour before the start.
- Infrastructure or configuration changes.

## 4. Form and test hypotheses

State each hypothesis with the evidence that supports it and what would
contradict it. For example: "the 1.8.2 release introduced a slow query" is
supported by a deploy minutes before the step and by slow-query warnings, and
contradicted if query latency stayed flat.
