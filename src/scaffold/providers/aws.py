"""AWS: Hive platform patches and Crossplane IAM user/policy/access key patches."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type-only: params imports providers at runtime
    from scaffold.params import ClusterParams

from scaffold.providers.base import Provider, dump, rename_ops, replace, target


class AWSProvider(Provider):
    name = "aws"
    help = "Amazon Web Services"
    control_plane_type = "m7i.4xlarge"
    worker_type = "m7i.2xlarge"

    def default_zones(self, region: str) -> list[str]:
        return [f"{region}a", f"{region}b", f"{region}c"]

    def clusterdeployment_ops(self, params: ClusterParams) -> list[dict]:
        return [replace("/spec/platform/aws/region", params.region)]

    def install_config_platforms(self, params: ClusterParams) -> tuple[dict, dict, dict]:
        zones = list(params.zones)
        return (
            {"aws": {"type": params.control_plane_type, "zones": zones}},
            {"aws": {
                "rootVolume": {"iops": 4000, "size": 100, "type": "gp3"},
                "type": params.worker_type,
                "zones": list(zones),
            }},
            {"aws": {"region": params.region}},
        )

    def machinepool_ops(self, params: ClusterParams) -> list[dict]:
        return [
            replace("/spec/platform/aws/type", params.worker_type),
            replace("/spec/platform/aws/zones", list(params.zones)),
        ]

    def crossplane_patches(self, params: ClusterParams) -> tuple[list[dict], dict[str, str]]:
        n = params.name
        user, policy = f"{n}-ocp-installer", f"{n}-openshift4installerpolicy"

        entries = [
            target("User", "cluster-placeholder-ocp-installer", "patches/user.yaml"),
            target("Policy", "cluster-placeholder-openshift4installerpolicy", "patches/policy.yaml"),
            target("UserPolicyAttachment", "cluster-placeholder-policy-attachment", "patches/policy-attachment.yaml"),
            target("AccessKey", "cluster-placeholder-access-key", "patches/access-key.yaml"),
        ]
        files = {
            "patches/user.yaml": dump(rename_ops(user, n)),
            "patches/policy.yaml": dump(rename_ops(policy, n)),
            "patches/policy-attachment.yaml": dump(rename_ops(f"{n}-policy-attachment", n) + [
                replace("/spec/forProvider/policyArnRef/name", policy),
                replace("/spec/forProvider/userRef/name", user),
            ]),
            "patches/access-key.yaml": dump(rename_ops(f"{n}-access-key", n) + [
                replace("/spec/forProvider/userRef/name", user),
                replace("/spec/writeConnectionSecretToRef/namespace", n),
            ]),
        }
        return entries, files
