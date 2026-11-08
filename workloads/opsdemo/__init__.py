"""OpsPilot demo workloads.

Three deliberately small services (checkout, payments, users) whose job is to
produce realistic, reproducible operational telemetry for OpsPilot to
investigate. Shared plumbing (config, logging, metrics, request IDs, failure
injection) lives in this package so each service module is only its routes.
"""
