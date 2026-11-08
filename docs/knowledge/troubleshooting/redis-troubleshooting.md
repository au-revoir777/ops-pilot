---
title: Redis troubleshooting guide
doc_type: troubleshooting
services: []
owner: sre
tags: [redis, cache, external-projects]
---

# Redis troubleshooting guide

The OpsPilot demo services do not use Redis. This guide applies to monitored
external projects that use Redis as a cache or session store.

## Symptoms

- Rising latency on endpoints that read from the cache, with a falling cache
  hit ratio (more requests fall through to the database).
- Connection errors or timeouts to Redis in application logs.
- Memory near `maxmemory` with high eviction counts (`evicted_keys` growing).

## Checks

1. Hit ratio: `keyspace_hits / (keyspace_hits + keyspace_misses)` from the Redis
   exporter. A sudden drop after a deploy often means a changed cache key format.
2. Latency: slow commands (`SLOWLOG GET`, read-only) and blocking commands such as
   `KEYS *` in application code.
3. Memory and evictions: eviction storms cause cache misses and database load.
4. Connections: `connected_clients` near the limit, or clients not reusing
   connections.

## Safe actions

- Roll back a release that changed cache keys or access patterns.
- Read-only inspection commands (`INFO`, `SLOWLOG GET`).

## Requires human approval

- `FLUSHALL` / `FLUSHDB`, restarting Redis, changing `maxmemory` or eviction policy.
