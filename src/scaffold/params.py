"""Cluster parameters shared by the CLI, generators, and cloud providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# (control plane replicas, worker replicas) per topology
TOPOLOGY_REPLICAS: dict[str, tuple[int, int]] = {
    "standard": (3, 3),
    "compact": (3, 0),
    "sno": (1, 0),
}

# Topologies whose cluster-templates base includes a worker MachinePool
WORKER_POOL_TOPOLOGIES = frozenset({"standard"})


@dataclass
class ClusterParams:
    name: str
    region: str
    tier: str
    cloud: str = "aws"
    topology: str = "standard"
    environment: str = "development"
    base_domain: str = "openshiftpartnerlabs.com"
    # None -> resolved from the cloud provider / topology in __post_init__
    control_plane_type: str | None = None
    worker_type: str | None = None
    control_plane_replicas: int | None = None
    worker_replicas: int | None = None
    image_set: str = "img4.21.13-x86-64-appsub"
    zones: list[str] | None = None
    htpasswd_provider_name: str | None = None
    # Cloud-specific settings (e.g. Azure subscription ID), keyed by option name
    provider_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Imported lazily: providers import this module
        from scaffold.providers import get_provider  # pylint: disable=import-outside-toplevel

        provider = get_provider(self.cloud)
        cp_replicas, worker_replicas = TOPOLOGY_REPLICAS.get(self.topology, TOPOLOGY_REPLICAS["standard"])
        if self.control_plane_replicas is None:
            self.control_plane_replicas = cp_replicas
        if self.worker_replicas is None:
            self.worker_replicas = worker_replicas
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

    @property
    def has_worker_pool(self) -> bool:
        return self.topology in WORKER_POOL_TOPOLOGIES
