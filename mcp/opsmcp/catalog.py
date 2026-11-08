"""Service catalog: declared ownership and dependencies for monitored services.

Loaded from YAML (``CATALOG_PATH``), so external projects are onboarded by
editing configuration, not code. Telemetry-observed dependencies are merged in
by the tools; the catalog only holds what people declared.

    services:
      checkout:
        project: opsdemo
        description: Order placement
        depends_on: [users, payments]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SERVICE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


class CatalogError(ValueError):
    pass


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    project: str | None = None
    description: str | None = None
    owner: str | None = None
    depends_on: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class ServiceCatalog:
    services: dict[str, CatalogEntry] = field(default_factory=dict)

    def get(self, name: str) -> CatalogEntry | None:
        return self.services.get(name)

    def dependents_of(self, name: str) -> list[str]:
        return sorted(s.name for s in self.services.values() if name in s.depends_on)

    @classmethod
    def from_yaml(cls, text: str) -> ServiceCatalog:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise CatalogError("service catalog is not valid YAML") from exc
        raw = data.get("services", {}) if isinstance(data, dict) else None
        if not isinstance(raw, dict):
            raise CatalogError("service catalog needs a 'services' mapping")
        services: dict[str, CatalogEntry] = {}
        for name, spec in raw.items():
            spec = spec or {}
            depends_on = spec.get("depends_on", []) or []
            if not SERVICE_NAME.match(str(name)) or not all(
                isinstance(d, str) and SERVICE_NAME.match(d) for d in depends_on
            ):
                raise CatalogError(f"invalid service name in catalog entry '{name}'")
            services[name] = CatalogEntry(
                name=name,
                project=spec.get("project"),
                description=spec.get("description"),
                owner=spec.get("owner"),
                depends_on=tuple(depends_on),
            )
        return cls(services)

    @classmethod
    def load(cls, path: Path) -> ServiceCatalog:
        if not path.is_file():
            raise CatalogError(f"service catalog not found at {path}")
        return cls.from_yaml(path.read_text(encoding="utf-8"))
