# Azure provider guide

This guide describes the status of Azure support, the credentials that `fleet-scaffold-cluster azure` generates, and the hub prerequisites, for engineers who evaluate or extend Azure support.

- Flags and an example command: [README, Azure](../README.md#azure).

> [!WARNING]
> Do not use Azure overlays for partner clusters. The installer credentials reach the spoke, where a partner with cluster-admin can change other clusters' DNS records. See [Azure status](#azure-status).

## Contents

- [Azure status](#azure-status)
- [Azure credential flow](#azure-credential-flow)
- [Azure hub prerequisites](#azure-hub-prerequisites)

## Azure status

The scaffold generates Azure overlays, but they must not be used for partner clusters yet:

- **Credentials reach the spoke.** install-config sets no `credentialsMode`, so OpenShift uses passthrough and stores the installer service principal in `kube-system/azure-credentials`. That principal is DNS Zone Contributor on the **shared** `--base-domain` zone. Any partner cluster-admin can rewrite other clusters' `api`/`*.apps` records, or add `_acme-challenge` records to get certificates for them. Its subscription-wide Reader role also exposes every other cluster's resources. This breaks the isolation rule AWS follows (see [AWS credentials](aws.md#aws-credentials-cluster-scoped-default)). The fix is the same model: `credentialsMode: Manual`, the installer principal stays on the hub, and per-operator principals scoped to `<name>-rg` and the cluster's own DNS record sets.
- **The fleet pipeline has no Azure support.** No Azure Crossplane providers on the hub, no RoleAssignment binding, no `azure-credentials` Secret, and no teardown of the Azure managed resources.
- **fleet-clusters' `cluster-templates/azure` is stale.** Validation now rejects overlays built against it.

## Azure credential flow

Each cluster gets its own service principal, scoped to its own resource group:

![Azure credential flow: Crossplane creates the ResourceGroup, Application, Principal, Password and paused RoleAssignments. The Password writes the Secret azure-credentials-raw. The Tekton pipeline copies the Principal objectId into the RoleAssignments and builds the Secret azure-credentials, which the Hive ClusterDeployment uses.](diagrams/azure-credential-flow.svg)

Mermaid source: [diagrams/azure-credential-flow.mmd](diagrams/azure-credential-flow.mmd). [diagrams/README.md](diagrams/README.md) describes how to edit the diagram.

| RoleAssignment            | Role                        | Scope                              |
|---------------------------|-----------------------------|------------------------------------|
| `<name>-contributor`          | Contributor                 | `<name>-rg`                        |
| `<name>-user-access-admin`    | User Access Administrator   | `<name>-rg`                        |
| `<name>-dns-zone-contributor` | DNS Zone Contributor        | `--base-domain` zone in `--base-domain-resource-group` |
| `<name>-reader`               | Reader                      | Subscription (installer validation, read-only) |

The installer installs into the pre-created, empty `<name>-rg` (`platform.azure.resourceGroupName`).

**The fleet Tekton pipeline must complete two steps** (Crossplane cannot do them with plain managed resources, because `provider-azure` RoleAssignments cannot reference a `provider-azuread` Principal):

1. For each `RoleAssignment` in the cluster namespace: set `spec.forProvider.principalId` to the Principal's `status.atProvider.objectId` and remove the `crossplane.io/paused` annotation.
2. Build Secret `azure-credentials` with key `osServicePrincipal.json`:
   ```json
   {
     "subscriptionId": "<--subscription-id>",
     "clientId": "<Application status.atProvider.clientId>",
     "clientSecret": "<azure-credentials-raw key attribute.value>",
     "tenantId": "<Principal status.atProvider.applicationTenantId>"
   }
   ```

If the overlays are synced by a GitOps tool, exclude `spec.forProvider.principalId` and the paused annotation on RoleAssignments from drift detection, or the sync will revert step 1.

## Azure hub prerequisites

- Crossplane providers `provider-azure-azure`, `provider-azure-authorization`, and `provider-azuread`, each with a `ProviderConfig` named `default`
- The provider identity needs Entra permission to create app registrations (e.g. `Application.ReadWrite.OwnedBy`) and Owner (or Contributor + User Access Administrator) on the subscription
- A public Azure DNS zone for `--base-domain` in `--base-domain-resource-group`
- Regional vCPU quota for the chosen VM family
