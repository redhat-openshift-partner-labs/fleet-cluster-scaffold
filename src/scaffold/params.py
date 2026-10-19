"""Cluster parameters shared by the CLI, generators, and cloud providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TOPOLOGIES = ("standard", "compact", "sno")


@dataclass
class ClusterParams:
    name: str
    region: str
    tier: str
    cloud: str = "aws"
    topology: str = "standard"
    environment: str = "development"
    base_domain: str = "openshiftpartnerlabs.com"
    # None -> resolved from the cloud provider in __post_init__
    control_plane_type: str | None = None
    worker_type: str | None = None
    control_plane_replicas: int = 3
    worker_replicas: int = 3
    image_set: str = "img4.21.13-x86-64-appsub"
    zones: list[str] | None = None
    htpasswd_provider_name: str | None = None
    # Cloud-specific settings (e.g. Azure subscription ID), keyed by option name
    provider_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Imported lazily: providers import this module
        from scaffold.providers import get_provider  # pylint: disable=import-outside-toplevel

        provider = get_provider(self.cloud)
        if self.control_plane_type is None:
            self.control_plane_type = provider.control_plane_type
        if self.worker_type is None:
            self.worker_type = provider.worker_type
        if self.zones is None:
            self.zones = provider.default_zones(self.region)

    @property
    def profile(self) -> str:
        """cluster-templates sub-path, e.g. ``aws/standard``."""
        return f"{self.cloud}/{self.topology}"
