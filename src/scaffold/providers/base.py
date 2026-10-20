"""Cloud provider interface and shared patch helpers."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:  # type-only: params imports providers at runtime
    from scaffold.params import ClusterParams


# Ownership label on every overlay resource (selector for per-cluster teardown)
CLUSTER_LABEL = "openshiftpartnerlabs.com/cluster"


def dump(obj: Any) -> str:
    return yaml.dump(obj, default_flow_style=False, sort_keys=False)


def replace(path: str, value: Any) -> dict[str, Any]:
    """JSON6902 replace op."""
    return {"op": "replace", "path": path, "value": value}


def rename_ops(name: str, namespace: str) -> list[dict[str, Any]]:
    """Ops every placeholder resource needs: concrete name and namespace."""
    return [replace("/metadata/name", name), replace("/metadata/namespace", namespace)]


def target(kind: str, name: str, path: str, group: str | None = None) -> dict[str, Any]:
    """Kustomize patch entry selecting a placeholder resource."""
    sel: dict[str, str] = {"kind": kind, "name": name}
    if group:
        sel = {"group": group, **sel}
    return {"target": sel, "path": path}


class Provider:
    """Cloud-specific pieces of an overlay. Subclass per cloud and register in providers/__init__.py."""

    name: str = ""
    help: str = ""
    implemented: bool = True
    control_plane_type: str = ""
    worker_type: str = ""

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        """Register cloud-specific CLI flags."""

    def options_from_args(self, parsed: argparse.Namespace) -> dict[str, Any]:  # pylint: disable=unused-argument
        """Extract cloud-specific flags into ClusterParams.provider_options."""
        return {}

    def validate(self, params: ClusterParams) -> None:
        """Raise ValueError for invalid cloud-specific input."""

    def default_zones(self, region: str) -> list[str]:
        raise NotImplementedError

    def clusterdeployment_ops(self, params: ClusterParams) -> list[dict[str, Any]]:
        """Ops for /spec/platform/<cloud> on the ClusterDeployment."""
        raise NotImplementedError

    def install_config_platforms(self, params: ClusterParams) -> tuple[dict, dict, dict]:
        """Return (controlPlane.platform, compute[worker].platform, platform) for install-config."""
        raise NotImplementedError

    def install_config_extra(self, params: ClusterParams) -> dict[str, Any]:  # pylint: disable=unused-argument
        """Additional top-level install-config fields (e.g. credentialsMode)."""
        return {}

    def crossplane_base_dir(self, params: ClusterParams) -> str:  # pylint: disable=unused-argument
        """cluster-templates/<profile>/ subdirectory holding the Crossplane base."""
        return "crossplane"

    def metadata(self, params: ClusterParams) -> dict[str, str]:  # pylint: disable=unused-argument
        """Per-cluster metadata.yaml keys read by the fleet pipelines."""
        return {"platform": self.name}

    def machinepool_ops(self, params: ClusterParams) -> list[dict[str, Any]]:
        """Ops for /spec/platform/<cloud> on the worker MachinePool."""
        raise NotImplementedError

    def crossplane_patches(self, params: ClusterParams) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """Return (kustomization patch entries, {relative file path: content})."""
        raise NotImplementedError


class PlannedProvider(Provider):  # pylint: disable=abstract-method
    """Placeholder for a cloud that has a subcommand but no generator yet."""

    implemented = False

    def __init__(self, name: str, help_text: str) -> None:
        self.name = name
        self.help = f"{help_text} (not yet supported)"

    def default_zones(self, region: str) -> list[str]:
        return []
