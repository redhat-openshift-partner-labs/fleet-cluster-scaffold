"""Azure: Hive platform patches and Crossplane per-cluster service principal patches.

Crossplane creates a per-cluster resource group, Entra application, service principal,
and client secret (written to azure-credentials-raw). RoleAssignments are created paused
with a placeholder principalId: provider-azure cannot reference a provider-azuread
Principal, so the fleet Tekton pipeline must patch in the principal's objectId and
remove the crossplane.io/paused annotation.
"""

from __future__ import annotations

import argparse
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # type-only: params imports providers at runtime
    from scaffold.params import ClusterParams

from scaffold.providers.base import Provider, dump, rename_ops, replace, target

_LOG = logging.getLogger("scaffold")

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

_AZUREAD_APPS = "applications.azuread.upbound.io"
_AZUREAD_SPS = "serviceprincipals.azuread.upbound.io"

# (name suffix, scope key). Roles are fixed in the base template; only scopes vary per cluster.
# Installer needs Contributor + User Access Administrator on its resource group, write access to
# the public DNS zone, and subscription-wide read for SKU/quota/region validation.
_ROLE_ASSIGNMENTS = (
    ("contributor", "rg"),
    ("user-access-admin", "rg"),
    ("dns-zone-contributor", "dns"),
    ("reader", "subscription"),
)


def resource_group_name(cluster_name: str) -> str:
    """Pre-created, installer-owned resource group for the cluster."""
    return f"{cluster_name}-rg"


class AzureProvider(Provider):
    name = "azure"
    help = "Microsoft Azure"
    control_plane_type = "Standard_D8s_v5"
    worker_type = "Standard_D8s_v5"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--subscription-id", required=True, help="Azure subscription ID the cluster is installed into")
        parser.add_argument(
            "--base-domain-resource-group",
            default="openshift-dns",
            help="Resource group holding the Azure DNS zone for --base-domain (default: %(default)s)",
        )
        parser.add_argument(
            "--cloud-name",
            default="AzurePublicCloud",
            choices=["AzurePublicCloud", "AzureUSGovernmentCloud"],
            help="Azure cloud environment (default: %(default)s)",
        )

    def options_from_args(self, parsed: argparse.Namespace) -> dict[str, str]:
        return {
            "subscription_id": parsed.subscription_id,
            "base_domain_resource_group": parsed.base_domain_resource_group,
            "cloud_name": parsed.cloud_name,
        }

    def validate(self, params: ClusterParams) -> None:
        sub = params.provider_options.get("subscription_id", "")
        if not _UUID_RE.match(sub):
            raise ValueError(f"Azure subscription ID {sub!r} is not a valid UUID.")
        if params.base_domain.lower() != params.base_domain:
            raise ValueError("Azure DNS zone names (--base-domain) must be lowercase.")
        _LOG.warning(
            "WARNING: Azure clusters use passthrough credentials: the installer service principal is stored on "
            "the spoke (kube-system/azure-credentials), and it can write the shared --base-domain DNS zone, "
            "so any cluster-admin can change other clusters' DNS records. The fleet pipeline does not support Azure yet."
        )

    def default_zones(self, region: str) -> list[str]:
        return ["1", "2", "3"]

    @staticmethod
    def _opts(params: ClusterParams) -> tuple[str, str, str]:
        o = params.provider_options
        return (
            o.get("subscription_id", "subscription-placeholder"),
            o.get("base_domain_resource_group", "openshift-dns"),
            o.get("cloud_name", "AzurePublicCloud"),
        )

    def metadata(self, params: ClusterParams) -> dict[str, str]:
        sub, dns_rg, _ = self._opts(params)
        # Read by the fleet pipeline: osServicePrincipal.json and the Azure DNS-01 ClusterIssuer
        return {**super().metadata(params), "azure-subscription-id": sub, "azure-dns-resource-group": dns_rg}

    def clusterdeployment_ops(self, params: ClusterParams) -> list[dict]:
        _, dns_rg, cloud = self._opts(params)
        return [
            replace("/spec/platform/azure/region", params.region),
            replace("/spec/platform/azure/baseDomainResourceGroupName", dns_rg),
            replace("/spec/platform/azure/cloudName", cloud),
        ]

    def install_config_platforms(self, params: ClusterParams) -> tuple[dict, dict, dict]:
        _, dns_rg, cloud = self._opts(params)
        zones = [str(z) for z in params.zones]
        return (
            {"azure": {"type": params.control_plane_type, "zones": zones}},
            {"azure": {
                "osDisk": {"diskSizeGB": 128, "diskType": "Premium_LRS"},
                "type": params.worker_type,
                "zones": list(zones),
            }},
            {"azure": {
                "baseDomainResourceGroupName": dns_rg,
                "cloudName": cloud,
                "region": params.region,
                "resourceGroupName": resource_group_name(params.name),
            }},
        )

    def machinepool_ops(self, params: ClusterParams) -> list[dict]:
        return [
            replace("/spec/platform/azure/type", params.worker_type),
            replace("/spec/platform/azure/zones", [str(z) for z in params.zones]),
        ]

    def crossplane_patches(self, params: ClusterParams) -> tuple[list[dict], dict[str, str]]:
        n = params.name
        sub, dns_rg, _ = self._opts(params)
        rg = resource_group_name(n)
        app = f"{n}-ocp-installer"
        scopes = {
            "rg": f"/subscriptions/{sub}/resourceGroups/{rg}",
            "dns": f"/subscriptions/{sub}/resourceGroups/{dns_rg}/providers/Microsoft.Network/dnszones/{params.base_domain}",
            "subscription": f"/subscriptions/{sub}",
        }

        entries = [
            target("ResourceGroup", "cluster-placeholder-rg", "patches/resource-group.yaml"),
            target("Application", "cluster-placeholder-ocp-installer", "patches/application.yaml", _AZUREAD_APPS),
            target("Principal", "cluster-placeholder-ocp-installer", "patches/service-principal.yaml", _AZUREAD_SPS),
            target("Password", "cluster-placeholder-client-secret", "patches/client-secret.yaml", _AZUREAD_APPS),
        ]
        files = {
            "patches/resource-group.yaml": dump(rename_ops(rg, n) + [
                replace("/spec/forProvider/location", params.region),
            ]),
            "patches/application.yaml": dump(rename_ops(app, n) + [
                replace("/spec/forProvider/displayName", app),
            ]),
            "patches/service-principal.yaml": dump(rename_ops(app, n) + [
                replace("/spec/forProvider/clientIdRef/name", app),
            ]),
            "patches/client-secret.yaml": dump(rename_ops(f"{n}-client-secret", n) + [
                replace("/spec/forProvider/applicationIdRef/name", app),
                replace("/spec/writeConnectionSecretToRef/namespace", n),
            ]),
        }
        for suffix, scope in _ROLE_ASSIGNMENTS:
            path = f"patches/role-assignment-{suffix}.yaml"
            entries.append(target("RoleAssignment", f"cluster-placeholder-{suffix}", path))
            files[path] = dump(rename_ops(f"{n}-{suffix}", n) + [
                replace("/spec/forProvider/scope", scopes[scope]),
            ])
        return entries, files
