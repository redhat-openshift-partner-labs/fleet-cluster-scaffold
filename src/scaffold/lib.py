"""Generate cluster overlay directories for Kustomize structure.

Standalone version — uses a shared cluster-templates directory for base
resources instead of copying templates into each cluster overlay.
Cloud-specific pieces are delegated to scaffold.providers.
"""

from __future__ import annotations

import os
import re

import yaml

from scaffold.params import TOPOLOGIES, ClusterParams
from scaffold.providers import PROVIDERS, get_provider
from scaffold.providers.base import dump, rename_ops, replace, target

__all__ = [
    "ClusterParams",
    "TOPOLOGIES",
    "generate_crossplane_patches",
    "generate_hive_patches",
    "generate_metadata",
    "get_default_zones",
    "validate_cluster_name",
    "validate_profile",
    "write_cluster_dir",
]


class _LiteralStr(str):
    """Marker subclass so yaml.dump uses literal block scalar style (|)."""


def _literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_LiteralStr, _literal_str_representer)

_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def validate_cluster_name(name: str) -> None:
    """Validate that *name* is a valid DNS-1123 label (RFC 1123).

    Raises ValueError if invalid.
    """
    if not name:
        raise ValueError("Cluster name must not be empty.")
    if len(name) > 63:
        raise ValueError(
            f"Cluster name must be at most 63 characters, got {len(name)}."
        )
    if not _DNS_LABEL_RE.match(name):
        raise ValueError(
            f"Cluster name {name!r} is not a valid DNS-1123 label. "
            "Use only lowercase letters, digits, and hyphens; "
            "must start and end with an alphanumeric character."
        )


def validate_profile(profile: str, cluster_templates_dir: str) -> None:
    """Validate that *profile* (``<cloud>/<topology>``) is implemented and its template directory exists.

    Raises ValueError if the cloud is unsupported or the directory is missing.
    """
    cloud = profile.split("/", 1)[0]
    provider = PROVIDERS.get(cloud)
    if provider is None or not provider.implemented:
        supported = ", ".join(f"{c}/*" for c, p in PROVIDERS.items() if p.implemented)
        raise ValueError(
            f"Profile {profile!r} is not supported. Supported profiles: {supported}."
        )
    tpl_dir = os.path.join(cluster_templates_dir, profile)
    if not os.path.isdir(tpl_dir):
        raise ValueError(
            f"Template directory for profile {profile!r} not found at {tpl_dir}."
        )


def get_default_zones(region: str, cloud: str = "aws") -> list[str]:
    return get_provider(cloud).default_zones(region)


def _resolve_base_resource_path(
    cluster_dir: str,
    subdir: str,
    cluster_templates_dir: str,
    profile: str,
) -> str:
    """Compute the relative path from <cluster_dir>/<subdir>/ to cluster-templates/<profile>/<subdir>."""
    abs_sub = os.path.abspath(os.path.join(cluster_dir, subdir))
    abs_tpl = os.path.abspath(os.path.join(cluster_templates_dir, profile, subdir))
    return os.path.relpath(abs_tpl, abs_sub)


def _kustomization(namespace: str, base_path: str, patches: list[dict]) -> str:
    return dump({
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "namespace": namespace,
        "resources": [base_path],
        "patches": patches,
    })


# ===================== hive patch generation =====================

def _install_config(params: ClusterParams) -> dict:
    cp_platform, worker_platform, platform = get_provider(params.cloud).install_config_platforms(params)
    worker = {"name": "worker", "platform": worker_platform, "replicas": params.worker_replicas}
    return {
        "apiVersion": "v1",
        "baseDomain": params.base_domain,
        "metadata": {"name": params.name},
        "controlPlane": {
            "name": "master",
            "platform": cp_platform,
            "replicas": params.control_plane_replicas,
        },
        "compute": [worker],
        "networking": {
            "clusterNetwork": [{"cidr": "10.128.0.0/14", "hostPrefix": 23}],
            "machineNetwork": [{"cidr": "10.0.0.0/16"}],
            "serviceNetwork": ["172.30.0.0/16"],
            "networkType": "OVNKubernetes",
        },
        "platform": platform,
        "publish": "External",
    }


def generate_hive_patches(params: ClusterParams, hive_base_path: str = "../base/hive") -> dict[str, str]:
    n = params.name
    provider = get_provider(params.cloud)

    entries = [
        {"path": "patches/install-config.yaml"},
        target("Secret", "cluster-placeholder-install-config", "patches/install-config-meta.yaml"),
        target("Namespace", "cluster-placeholder", "patches/namespace.yaml"),
        target("ClusterDeployment", "cluster-placeholder", "patches/clusterdeployment.yaml"),
        target("MachinePool", "cluster-placeholder-worker", "patches/machinepool-worker.yaml"),
        target("ManagedCluster", "cluster-placeholder", "patches/managedcluster.yaml"),
        target("KlusterletAddonConfig", "cluster-placeholder", "patches/klusterletaddonconfig.yaml"),
    ]

    patches: dict[str, str] = {"kustomization.yaml": _kustomization(n, hive_base_path, entries)}

    patches["patches/clusterdeployment.yaml"] = dump(
        rename_ops(n, n)
        + [replace("/spec/clusterName", n)]
        + provider.clusterdeployment_ops(params)
        + [
            replace("/spec/provisioning/installConfigSecretRef/name", f"{n}-install-config"),
            replace("/spec/provisioning/sshPrivateKeySecretRef/name", f"{n}-ssh-key"),
            replace("/spec/provisioning/imageSetRef/name", params.image_set),
        ]
    )

    # Strategic-merge patch on the placeholder Secret; renamed afterwards by install-config-meta
    patches["patches/install-config.yaml"] = dump({
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": "cluster-placeholder-install-config",
            "namespace": "cluster-placeholder",
        },
        "type": "Opaque",
        "stringData": {"install-config.yaml": _LiteralStr(dump(_install_config(params)))},
    })

    patches["patches/install-config-meta.yaml"] = dump(rename_ops(f"{n}-install-config", n))
    patches["patches/namespace.yaml"] = dump([replace("/metadata/name", n)])
    patches["patches/klusterletaddonconfig.yaml"] = dump(rename_ops(n, n) + [
        replace("/spec/clusterName", n),
        replace("/spec/clusterNamespace", n),
    ])

    patches["patches/machinepool-worker.yaml"] = dump(
        rename_ops(f"{n}-worker", n)
        + [replace("/spec/clusterDeploymentRef/name", n)]
        + provider.machinepool_ops(params)
        + [replace("/spec/replicas", params.worker_replicas)]
    )

    patches["patches/managedcluster.yaml"] = dump([
        replace("/metadata/name", n),
        {"op": "add", "path": "/metadata/labels/name", "value": n},
        {"op": "add", "path": "/metadata/labels/tier", "value": params.tier},
        {"op": "add", "path": "/metadata/labels/environment", "value": params.environment},
        {"op": "add", "path": "/metadata/labels/region", "value": params.region},
    ])

    return patches


# ===================== crossplane patch generation =====================

def generate_crossplane_patches(params: ClusterParams, crossplane_base_path: str = "../base/crossplane") -> dict[str, str]:
    entries, files = get_provider(params.cloud).crossplane_patches(params)
    return {"kustomization.yaml": _kustomization(params.name, crossplane_base_path, entries), **files}


# ===================== metadata generation =====================

def generate_metadata(params: ClusterParams) -> str:
    meta: dict[str, str] = {}
    if params.htpasswd_provider_name:
        meta["htpasswd-provider-name"] = params.htpasswd_provider_name
    return dump(meta)


# ===================== directory writing =====================

def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def write_cluster_dir(base_path: str, params: ClusterParams, cluster_templates_dir: str = "cluster-templates") -> str:
    cluster_dir = os.path.join(base_path, params.name)
    profile = params.profile

    hive_base_path = _resolve_base_resource_path(cluster_dir, "hive", cluster_templates_dir, profile)
    crossplane_base_path = _resolve_base_resource_path(cluster_dir, "crossplane", cluster_templates_dir, profile)

    top_kustomization = dump({
        "apiVersion": "kustomize.config.k8s.io/v1beta1",
        "kind": "Kustomization",
        "resources": ["crossplane/", "hive/"],
    })

    _write(os.path.join(cluster_dir, "kustomization.yaml"), top_kustomization)
    _write(os.path.join(cluster_dir, "metadata.yaml"), generate_metadata(params))

    for rel_path, content in generate_hive_patches(params, hive_base_path).items():
        _write(os.path.join(cluster_dir, "hive", rel_path), content)

    for rel_path, content in generate_crossplane_patches(params, crossplane_base_path).items():
        _write(os.path.join(cluster_dir, "crossplane", rel_path), content)

    return cluster_dir
