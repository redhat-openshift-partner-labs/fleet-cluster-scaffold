"""Generate cluster overlay directories for Kustomize structure.

Standalone version — uses a shared cluster-templates directory for base
resources instead of copying templates into each cluster overlay.
"""

from __future__ import annotations

import os

import yaml

from scaffold.models import ClusterParams, get_default_zones, validate_cluster_name


class _LiteralStr(str):
    """Marker subclass so yaml.dump uses literal block scalar style (|)."""


def _literal_str_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_LiteralStr, _literal_str_representer)


def validate_profile(profile: str, cluster_templates_dir: str) -> None:
    """Validate that *profile* is a supported AWS profile and its template directory exists.

    Raises ValueError if the profile is not AWS-based or the directory is missing.
    """
    if not (profile.startswith("aws") ):
        raise ValueError(
            f"Profile {profile!r} is not supported. "
            "Only AWS profiles (aws/*) are currently supported."
        )
    tpl_dir = os.path.join(cluster_templates_dir, profile)
    if not os.path.isdir(tpl_dir):
        raise ValueError(
            f"Template directory for profile {profile!r} not found at {tpl_dir}."
        )


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


# ===================== hive patch generation =====================

# TODO: AWS-specific — parameterize for Azure/GCP when multi-cloud support is added
def generate_hive_patches(params: ClusterParams, hive_base_path: str = "../base/hive") -> dict[str, str]:
    n = params.name
    patches: dict[str, str] = {}

    patches["kustomization.yaml"] = yaml.dump(
        {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "namespace": n,
            "resources": [hive_base_path],
            "patches": [
                {"path": "patches/install-config.yaml"},
                {
                    "target": {
                        "kind": "Secret",
                        "name": "cluster-placeholder-install-config",
                    },
                    "path": "patches/install-config-meta.yaml",
                },
                {
                    "target": {"kind": "Namespace", "name": "cluster-placeholder"},
                    "path": "patches/namespace.yaml",
                },
                {
                    "target": {
                        "kind": "ClusterDeployment",
                        "name": "cluster-placeholder",
                    },
                    "path": "patches/clusterdeployment.yaml",
                },
                {
                    "target": {
                        "kind": "MachinePool",
                        "name": "cluster-placeholder-worker",
                    },
                    "path": "patches/machinepool-worker.yaml",
                },
                {
                    "target": {
                        "kind": "ManagedCluster",
                        "name": "cluster-placeholder",
                    },
                    "path": "patches/managedcluster.yaml",
                },
                {
                    "target": {
                        "kind": "KlusterletAddonConfig",
                        "name": "cluster-placeholder",
                    },
                    "path": "patches/klusterletaddonconfig.yaml",
                },
            ],
        },
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/clusterdeployment.yaml"] = yaml.dump(
        [
            {"op": "replace", "path": "/metadata/name", "value": n},
            {"op": "replace", "path": "/metadata/namespace", "value": n},
            {"op": "replace", "path": "/spec/clusterName", "value": n},
            {
                "op": "replace",
                "path": "/spec/platform/aws/region",
                "value": params.region,
            },
            {
                "op": "replace",
                "path": "/spec/provisioning/installConfigSecretRef/name",
                "value": f"{n}-install-config",
            },
            {
                "op": "replace",
                "path": "/spec/provisioning/sshPrivateKeySecretRef/name",
                "value": f"{n}-ssh-key",
            },
            {
                "op": "replace",
                "path": "/spec/provisioning/imageSetRef/name",
                "value": params.image_set,
            },
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    zones = params.zones or get_default_zones(params.region)
    install_config = {
        "apiVersion": "v1",
        "baseDomain": params.base_domain,
        "metadata": {"name": n},
        "controlPlane": {
            "name": "master",
            "platform": {
                "aws": {
                    "type": params.control_plane_type,
                    "zones": list(zones),
                }
            },
            "replicas": params.control_plane_replicas,
        },
        "compute": [
            {
                "name": "worker",
                "platform": {
                    "aws": {
                        "rootVolume": {"iops": 4000, "size": 100, "type": "gp3"},
                        "type": params.worker_type,
                        "zones": list(zones),
                    }
                },
                "replicas": params.worker_replicas,
            }
        ],
        "networking": {
            "clusterNetwork": [{"cidr": "10.128.0.0/14", "hostPrefix": 23}],
            "machineNetwork": [{"cidr": "10.0.0.0/16"}],
            "serviceNetwork": ["172.30.0.0/16"],
            "networkType": "OVNKubernetes",
        },
        "platform": {"aws": {"region": params.region}},
        "publish": "External",
    }

    patches["patches/install-config.yaml"] = yaml.dump(
        {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": "cluster-placeholder-install-config",
                "namespace": "cluster-placeholder",
            },
            "type": "Opaque",
            "stringData": {
                "install-config.yaml": _LiteralStr(
                    yaml.dump(install_config, default_flow_style=False, sort_keys=False)
                )
            },
        },
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/install-config-meta.yaml"] = yaml.dump(
        [
            {
                "op": "replace",
                "path": "/metadata/name",
                "value": f"{n}-install-config",
            },
            {"op": "replace", "path": "/metadata/namespace", "value": n},
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/namespace.yaml"] = yaml.dump(
        [{"op": "replace", "path": "/metadata/name", "value": n}],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/klusterletaddonconfig.yaml"] = yaml.dump(
        [
            {"op": "replace", "path": "/metadata/name", "value": n},
            {"op": "replace", "path": "/metadata/namespace", "value": n},
            {"op": "replace", "path": "/spec/clusterName", "value": n},
            {"op": "replace", "path": "/spec/clusterNamespace", "value": n},
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/machinepool-worker.yaml"] = yaml.dump(
        [
            {"op": "replace", "path": "/metadata/name", "value": f"{n}-worker"},
            {"op": "replace", "path": "/metadata/namespace", "value": n},
            {"op": "replace", "path": "/spec/clusterDeploymentRef/name", "value": n},
            {
                "op": "replace",
                "path": "/spec/platform/aws/type",
                "value": params.worker_type,
            },
            {
                "op": "replace",
                "path": "/spec/platform/aws/zones",
                "value": list(zones),
            },
            {
                "op": "replace",
                "path": "/spec/replicas",
                "value": params.worker_replicas,
            },
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/managedcluster.yaml"] = yaml.dump(
        [
            {"op": "replace", "path": "/metadata/name", "value": n},
            {"op": "add", "path": "/metadata/labels/name", "value": n},
            {"op": "add", "path": "/metadata/labels/tier", "value": params.tier},
            {
                "op": "add",
                "path": "/metadata/labels/environment",
                "value": params.environment,
            },
            {"op": "add", "path": "/metadata/labels/region", "value": params.region},
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    return patches


# ===================== crossplane patch generation =====================

# TODO: AWS-specific — parameterize for Azure/GCP when multi-cloud support is added
def generate_crossplane_patches(params: ClusterParams, crossplane_base_path: str = "../base/crossplane") -> dict[str, str]:
    n = params.name
    patches: dict[str, str] = {}

    patches["kustomization.yaml"] = yaml.dump(
        {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "namespace": n,
            "resources": [crossplane_base_path],
            "patches": [
                {
                    "target": {
                        "kind": "User",
                        "name": "cluster-placeholder-ocp-installer",
                    },
                    "path": "patches/user.yaml",
                },
                {
                    "target": {
                        "kind": "Policy",
                        "name": "cluster-placeholder-openshift4installerpolicy",
                    },
                    "path": "patches/policy.yaml",
                },
                {
                    "target": {
                        "kind": "UserPolicyAttachment",
                        "name": "cluster-placeholder-policy-attachment",
                    },
                    "path": "patches/policy-attachment.yaml",
                },
                {
                    "target": {
                        "kind": "AccessKey",
                        "name": "cluster-placeholder-access-key",
                    },
                    "path": "patches/access-key.yaml",
                },
            ],
        },
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/user.yaml"] = yaml.dump(
        [
            {
                "op": "replace",
                "path": "/metadata/name",
                "value": f"{n}-ocp-installer",
            },
            {"op": "replace", "path": "/metadata/namespace", "value": n},
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/policy.yaml"] = yaml.dump(
        [
            {
                "op": "replace",
                "path": "/metadata/name",
                "value": f"{n}-openshift4installerpolicy",
            },
            {"op": "replace", "path": "/metadata/namespace", "value": n},
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/policy-attachment.yaml"] = yaml.dump(
        [
            {
                "op": "replace",
                "path": "/metadata/name",
                "value": f"{n}-policy-attachment",
            },
            {"op": "replace", "path": "/metadata/namespace", "value": n},
            {
                "op": "replace",
                "path": "/spec/forProvider/policyArnRef/name",
                "value": f"{n}-openshift4installerpolicy",
            },
            {
                "op": "replace",
                "path": "/spec/forProvider/userRef/name",
                "value": f"{n}-ocp-installer",
            },
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    patches["patches/access-key.yaml"] = yaml.dump(
        [
            {
                "op": "replace",
                "path": "/metadata/name",
                "value": f"{n}-access-key",
            },
            {"op": "replace", "path": "/metadata/namespace", "value": n},
            {
                "op": "replace",
                "path": "/spec/forProvider/userRef/name",
                "value": f"{n}-ocp-installer",
            },
            {
                "op": "replace",
                "path": "/spec/writeConnectionSecretToRef/namespace",
                "value": n,
            },
        ],
        default_flow_style=False,
        sort_keys=False,
    )

    return patches


# ===================== metadata generation =====================

def generate_metadata(params: ClusterParams) -> str:
    meta: dict[str, str] = {}
    if params.htpasswd_provider_name:
        meta["htpasswd-provider-name"] = params.htpasswd_provider_name
    return yaml.dump(meta, default_flow_style=False, sort_keys=False)


# ===================== directory writing =====================

def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def write_cluster_dir(base_path: str, params: ClusterParams, cluster_templates_dir: str = "cluster-templates") -> str:
    cluster_dir = os.path.join(base_path, params.name)
    profile = params.profile or "aws/standard"

    hive_base_path = _resolve_base_resource_path(cluster_dir, "hive", cluster_templates_dir, profile)
    crossplane_base_path = _resolve_base_resource_path(cluster_dir, "crossplane", cluster_templates_dir, profile)

    top_kustomization = yaml.dump(
        {
            "apiVersion": "kustomize.config.k8s.io/v1beta1",
            "kind": "Kustomization",
            "resources": ["crossplane/", "hive/"],
        },
        default_flow_style=False,
        sort_keys=False,
    )

    hive_patches = generate_hive_patches(params, hive_base_path)
    crossplane_patches = generate_crossplane_patches(params, crossplane_base_path)

    _write(os.path.join(cluster_dir, "kustomization.yaml"), top_kustomization)
    _write(os.path.join(cluster_dir, "metadata.yaml"), generate_metadata(params))

    for rel_path, content in hive_patches.items():
        _write(os.path.join(cluster_dir, "hive", rel_path), content)

    for rel_path, content in crossplane_patches.items():
        _write(os.path.join(cluster_dir, "crossplane", rel_path), content)

    return cluster_dir
