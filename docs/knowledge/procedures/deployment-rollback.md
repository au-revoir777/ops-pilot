---
title: Deployment rollback procedure
doc_type: procedure
services: [checkout, payments, users]
owner: sre
tags: [rollback, deployment, mitigation]
---

# Deployment rollback procedure

Roll back when an incident starts shortly after a release and the evidence
points at the release (new errors, a query regression, a latency step).
Rollback is a mitigation; the fix comes afterwards.

## Before rolling back

1. Identify the current and previous versions from `app_info` and the
   deployment history.
2. Confirm the previous version was healthy (its latency and error ratio before
   the deploy).
3. Check for irreversible changes in the release, especially database
   migrations. If the release ran a migration that is not backward compatible,
   escalate instead of rolling back.
4. Announce the rollback in the incident channel.

## Rolling back (requires human approval)

1. Redeploy the previous image tag for the affected service only.
2. Watch p95 latency, error ratio and `app_info` for the next 10 minutes.
3. Confirm the version label switched back and the symptom recovered.

## After rolling back

- Keep the bad version blocked from redeploying until a fix is reviewed.
- Record the timeline for the postmortem.

OpsPilot only recommends a rollback; it never performs one without explicit
human approval.
