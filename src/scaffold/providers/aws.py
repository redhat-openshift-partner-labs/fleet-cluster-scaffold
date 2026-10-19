"""AWS: Hive platform patches and Crossplane IAM patches.

Two credential modes:
- scoped (default): credentialsMode Manual, cluster-scoped per-operator IAM users and BYO node
  roles (see aws_policies). Nothing on the spoke can act on another cluster's resources.
- legacy: Mint mode with the account-admin installer policy. Rollback only; the installer key
  lands on the spoke in kube-system/aws-creds.
"""

from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type-only: params imports providers at runtime
    from scaffold.params import ClusterParams

from scaffold.providers import aws_policies as pol
from scaffold.providers.base import Provider, dump, rename_ops, replace, target

_LOG = logging.getLogger("scaffold")

SCOPED, LEGACY = "scoped", "legacy"

# (User, Policy, UserPolicyAttachment, AccessKey) placeholder names in the legacy and scoped installer bases
_INSTALLER_PLACEHOLDERS = (
    "cluster-placeholder-ocp-installer",
    "cluster-placeholder-openshift4installerpolicy",
    "cluster-placeholder-policy-attachment",
    "cluster-placeholder-access-key",
)


def _escape(key: str) -> str:
    """JSON pointer escaping for map keys containing '/'."""
    return key.replace("~", "~0").replace("/", "~1")


def _installer_names(n: str) -> tuple[str, str, str, str]:
    return f"{n}-ocp-installer", f"{n}-openshift4installerpolicy", f"{n}-policy-attachment", f"{n}-access-key"


def manifests_secret_name(cluster_name: str) -> str:
    """Secret (built by the fleet pipeline) holding the operator credential manifests for Hive."""
    return f"{cluster_name}-cloud-credentials-manifests"


class AWSProvider(Provider):
    name = "aws"
    help = "Amazon Web Services"
    control_plane_type = "m7i.4xlarge"
    worker_type = "m7i.2xlarge"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--legacy-mint-credentials",
            action="store_true",
            default=False,
            help="ROLLBACK ONLY: Mint mode with the account-admin installer policy (key is stored on the spoke)",
        )

    def options_from_args(self, parsed: argparse.Namespace) -> dict[str, str]:
        return {"credentials_mode": LEGACY if parsed.legacy_mint_credentials else SCOPED}

    @staticmethod
    def scoped(params: ClusterParams) -> bool:
        return params.provider_options.get("credentials_mode", SCOPED) == SCOPED

    def validate(self, params: ClusterParams) -> None:
        if not self.scoped(params):
            _LOG.warning(
                "WARNING: --legacy-mint-credentials stores an account-admin AWS key on the spoke "
                "(kube-system/aws-creds); any cluster-admin can use it across the whole account."
            )
            return
        if len(params.name) + pol.MAX_NAME_SUFFIX > pol.IAM_NAME_MAX:
            raise ValueError(
                f"Cluster name {params.name!r} is too long for scoped AWS credentials: IAM names "
                f"'<name>-<operator>' must fit in {pol.IAM_NAME_MAX} characters "
                f"(max name length {pol.IAM_NAME_MAX - pol.MAX_NAME_SUFFIX})."
            )

    def default_zones(self, region: str) -> list[str]:
        return [f"{region}a", f"{region}b", f"{region}c"]

    def clusterdeployment_ops(self, params: ClusterParams) -> list[dict]:
        ops = [replace("/spec/platform/aws/region", params.region)]
        if self.scoped(params):
            ops.append({
                "op": "add",
                "path": "/spec/provisioning/manifestsSecretRef",
                "value": {"name": manifests_secret_name(params.name)},
            })
        return ops

    def install_config_platforms(self, params: ClusterParams) -> tuple[dict, dict, dict]:
        zones = list(params.zones)
        cp: dict = {"type": params.control_plane_type, "zones": zones}
        worker: dict = {
            "rootVolume": {"iops": 4000, "size": 100, "type": "gp3"},
            "type": params.worker_type,
            "zones": list(zones),
        }
        platform: dict = {"region": params.region}
        if self.scoped(params):
            cp["iamRole"] = f"{params.name}-master-role"
            worker["iamRole"] = f"{params.name}-worker-role"
            platform["userTags"] = {pol.TAG_KEY: params.name}
            platform["propagateUserTags"] = True
        return {"aws": cp}, {"aws": worker}, {"aws": platform}

    def install_config_extra(self, params: ClusterParams) -> dict:
        return {"credentialsMode": "Manual"} if self.scoped(params) else {}

    def machinepool_ops(self, params: ClusterParams) -> list[dict]:
        ops = [
            replace("/spec/platform/aws/type", params.worker_type),
            replace("/spec/platform/aws/zones", list(params.zones)),
        ]
        if self.scoped(params):
            ops.append({"op": "add", "path": "/spec/platform/aws/userTags", "value": {pol.TAG_KEY: params.name}})
        return ops

    def crossplane_base_dir(self, params: ClusterParams) -> str:
        return "crossplane-scoped" if self.scoped(params) else "crossplane"

    def metadata(self, params: ClusterParams) -> dict[str, str]:
        return {**super().metadata(params), "aws-credentials-mode": SCOPED if self.scoped(params) else LEGACY}

    def crossplane_patches(self, params: ClusterParams) -> tuple[list[dict], dict[str, str]]:
        if self.scoped(params):
            return self._scoped_crossplane_patches(params)
        return self._legacy_crossplane_patches(params)

    @staticmethod
    def _legacy_crossplane_patches(params: ClusterParams) -> tuple[list[dict], dict[str, str]]:
        n = params.name
        user, policy, attach, key = _installer_names(n)
        p_user, p_policy, p_attach, p_key = _INSTALLER_PLACEHOLDERS

        entries = [
            target("User", p_user, "patches/user.yaml"),
            target("Policy", p_policy, "patches/policy.yaml"),
            target("UserPolicyAttachment", p_attach, "patches/policy-attachment.yaml"),
            target("AccessKey", p_key, "patches/access-key.yaml"),
        ]
        files = {
            "patches/user.yaml": dump(rename_ops(user, n)),
            "patches/policy.yaml": dump(rename_ops(policy, n)),
            "patches/policy-attachment.yaml": dump(rename_ops(attach, n) + [
                replace("/spec/forProvider/policyArnRef/name", policy),
                replace("/spec/forProvider/userRef/name", user),
            ]),
            "patches/access-key.yaml": dump(rename_ops(key, n) + [
                replace("/spec/forProvider/userRef/name", user),
                replace("/spec/writeConnectionSecretToRef/namespace", n),
            ]),
        }
        return entries, files

    @staticmethod
    def _scoped_crossplane_patches(params: ClusterParams) -> tuple[list[dict], dict[str, str]]:
        n, region, domain = params.name, params.region, params.base_domain
        tag_op = replace(f"/spec/forProvider/tags/{_escape(pol.TAG_KEY)}", n)
        entries: list[dict] = []
        files: dict[str, str] = {}

        def add(kind: str, placeholder: str, path: str, ops: list[dict]) -> None:
            entries.append(target(kind, placeholder, path))
            files[path] = dump(ops)

        def user_set(group: str, placeholders: tuple[str, ...], names: tuple[str, ...], policy_doc: dict,
                     secret: str | None = None) -> None:
            """Patches for one User/Policy/UserPolicyAttachment/AccessKey set."""
            user, policy, attach, key = names
            p_user, p_policy, p_attach, p_key = placeholders
            add("User", p_user, f"patches/{group}/user.yaml", rename_ops(user, n) + [tag_op])
            add("Policy", p_policy, f"patches/{group}/policy.yaml",
                rename_ops(policy, n) + [tag_op, replace("/spec/forProvider/policy", pol.render(policy_doc))])
            add("UserPolicyAttachment", p_attach, f"patches/{group}/attachment.yaml", rename_ops(attach, n) + [
                replace("/spec/forProvider/policyArnRef/name", policy),
                replace("/spec/forProvider/userRef/name", user),
            ])
            key_ops = rename_ops(key, n) + [
                replace("/spec/forProvider/userRef/name", user),
                replace("/spec/writeConnectionSecretToRef/namespace", n),
            ]
            if secret:
                key_ops.append(replace("/spec/writeConnectionSecretToRef/name", secret))
            add("AccessKey", p_key, f"patches/{group}/access-key.yaml", key_ops)

        # Installer keeps the legacy resource names so existing pipeline tasks keep working
        user_set("installer", _INSTALLER_PLACEHOLDERS, _installer_names(n), pol.installer_policy(n))

        for role, doc in (("master", pol.master_role_policy(n, region, domain)), ("worker", pol.worker_role_policy())):
            add("Role", f"cluster-placeholder-{role}-role", f"patches/node-roles/{role}-role.yaml",
                rename_ops(f"{n}-{role}-role", n) + [
                    tag_op,
                    replace("/spec/forProvider/inlinePolicy/0/name", f"{n}-{role}-policy"),
                    replace("/spec/forProvider/inlinePolicy/0/policy", pol.render(doc)),
                ])

        for c in pol.COMPONENTS:
            base = f"{n}-{c.key}"
            placeholder = f"cluster-placeholder-{c.key}"
            user_set(
                c.key,
                (placeholder, f"{placeholder}-policy", f"{placeholder}-attachment", f"{placeholder}-access-key"),
                (base, f"{base}-policy", f"{base}-attachment", f"{base}-access-key"),
                pol.component_policy(c.key, n, region, domain),
                secret=f"{base}-credentials-raw",
            )
        return entries, files
