# fleet-cluster-scaffold

Standalone CLI tool for scaffolding OpenShift cluster overlay directories with Kustomize. Generates all the Hive and Crossplane resources needed to provision a cluster on AWS or Azure, without depending on the fleet monorepo.

## What it does

Given a cloud, cluster name, region, and tier, `fleet-scaffold-cluster` generates a complete Kustomize overlay directory containing:

- **Hive resources** -- ClusterDeployment, MachinePool, ManagedCluster, KlusterletAddonConfig, install-config Secret, and Namespace patches
- **Crossplane resources** -- per-cluster installer credentials
  - AWS: IAM User, Policy, UserPolicyAttachment, and AccessKey
  - Azure: ResourceGroup, Entra Application, ServicePrincipal, client secret, and RoleAssignments
- **Cluster metadata** -- optional metadata such as the htpasswd identity provider name

Each overlay references shared base resources in `cluster-templates/<cloud>/<topology>/` via relative paths, so clusters stay lightweight while sharing common definitions.

## Requirements

- Python 3.11+
- [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/) (for post-scaffold validation; skip with `--skip-validation`)

## Installation

```bash
pip install .
```

This installs the `fleet-scaffold-cluster` command.

## Usage

```
fleet-scaffold-cluster CLOUD --name NAME --region REGION --tier TIER [options]
```

| Cloud      | Status              |
|------------|---------------------|
| `aws`      | Supported           |
| `azure`    | Supported           |
| `gcp`      | Planned (exits 1)   |
| `ibmcloud` | Planned (exits 1)   |

Run `fleet-scaffold-cluster CLOUD --help` for the full flag list of a cloud.

### Quick start

```bash
# AWS
fleet-scaffold-cluster aws --name my-cluster --region us-east-1 --tier base

# Azure
fleet-scaffold-cluster azure --name my-cluster --region eastus2 --tier base \
  --subscription-id 00000000-0000-0000-0000-000000000000
```

This creates `./my-cluster/` with the full Kustomize overlay structure and validates it with `kustomize build`.

### Common arguments (all clouds)

| Flag                       | Default                      | Description                                                  |
|----------------------------|------------------------------|--------------------------------------------------------------|
| `--name`                   | *(required)*                 | Cluster name (valid DNS-1123 label: lowercase alphanumeric and hyphens, 1-63 chars) |
| `--region`                 | *(required)*                 | Cloud region (e.g. `us-east-1`, `eastus2`)                   |
| `--tier`                   | *(required)*                 | Cluster tier: `base`, `virt`, `ai`                           |
| `--topology`               | `standard`                   | `standard`, `compact`, or `sno`; selects `cluster-templates/<cloud>/<topology>` |
| `--environment`            | `development`                | Environment label applied to ManagedCluster                  |
| `--base-domain`            | `openshiftpartnerlabs.com`   | Cluster base DNS domain                                      |
| `--control-plane-type`     | cloud-specific               | Instance type for control plane nodes                        |
| `--worker-type`            | cloud-specific               | Instance type for worker nodes                               |
| `--control-plane-replicas` | topology-specific            | `3` (standard, compact) or `1` (sno)                         |
| `--worker-replicas`        | topology-specific            | `3` (standard) or `0` (compact, sno)                         |
| `--image-set`              | `img4.21.13-x86-64-appsub`   | OpenShift ClusterImageSet name                               |
| `--zones`                  | cloud-specific               | Comma-separated zone list                                    |
| `--htpasswd-provider-name` | *(none)*                     | Display name for the htpasswd identity provider              |
| `--base-path`              | `.`                          | Parent directory for the cluster overlay                     |
| `--cluster-templates-dir`  | `cluster-templates`          | Path to shared cluster templates directory                   |
| `--force`                  |                              | Overwrite an existing cluster directory                      |
| `--skip-validation`        |                              | Skip `kustomize build` validation after scaffolding          |

### AWS

| Setting                | Default                  |
|------------------------|--------------------------|
| `--control-plane-type` | `m7i.4xlarge`            |
| `--worker-type`        | `m7i.2xlarge`            |
| `--zones`              | `<region>a,b,c`          |

```bash
fleet-scaffold-cluster aws \
  --name prod-east-01 \
  --region us-east-2 \
  --tier ai \
  --topology standard \
  --environment production \
  --control-plane-type m7i.8xlarge \
  --worker-type m7i.4xlarge \
  --worker-replicas 6 \
  --zones us-east-2a,us-east-2b \
  --htpasswd-provider-name "Acme Corp"
```

### Azure

| Flag                           | Default             | Description                                              |
|--------------------------------|---------------------|----------------------------------------------------------|
| `--subscription-id`            | *(required)*        | Subscription the cluster is installed into (UUID)        |
| `--base-domain-resource-group` | `openshift-dns`     | Resource group holding the Azure DNS zone for `--base-domain` |
| `--cloud-name`                 | `AzurePublicCloud`  | `AzurePublicCloud` or `AzureUSGovernmentCloud`           |
| `--control-plane-type`         | `Standard_D8s_v5`   |                                                          |
| `--worker-type`                | `Standard_D8s_v5`   |                                                          |
| `--zones`                      | `1,2,3`             | The region must support availability zones               |

```bash
fleet-scaffold-cluster azure \
  --name dev-az-01 \
  --region eastus2 \
  --tier base \
  --topology compact \
  --subscription-id 00000000-0000-0000-0000-000000000000 \
  --base-domain-resource-group openshift-dns
```

#### Azure credential flow

Each cluster gets its own service principal, scoped to its own resource group:

```mermaid
flowchart LR
  RG["ResourceGroup<br/>&lt;name&gt;-rg"]
  APP["Application<br/>&lt;name&gt;-ocp-installer"] -->|clientIdRef| SP["Principal"]
  APP -->|applicationIdRef| PW["Password<br/>&lt;name&gt;-client-secret"]
  PW -->|connection secret| RAW["azure-credentials-raw"]
  SP -.->|"objectId (Tekton)"| RA["RoleAssignments<br/>(paused)"]
  RAW -->|Tekton| CRED["azure-credentials<br/>osServicePrincipal.json"]
  CRED --> CD["Hive ClusterDeployment"]
```

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

#### Azure hub prerequisites

- Crossplane providers `provider-azure-azure`, `provider-azure-authorization`, and `provider-azuread`, each with a `ProviderConfig` named `default`
- The provider identity needs Entra permission to create app registrations (e.g. `Application.ReadWrite.OwnedBy`) and Owner (or Contributor + User Access Administrator) on the subscription
- A public Azure DNS zone for `--base-domain` in `--base-domain-resource-group`
- Regional vCPU quota for the chosen VM family

## Generated directory structure

```
<cluster-name>/
  kustomization.yaml            # aggregates hive/ and crossplane/
  metadata.yaml                 # cluster metadata (e.g. htpasswd provider name)
  hive/
    kustomization.yaml           # references cluster-templates/<cloud>/<topology>/hive
    patches/
      clusterdeployment.yaml
      install-config.yaml
      install-config-meta.yaml
      klusterletaddonconfig.yaml
      machinepool-worker.yaml    # standard topology only
      managedcluster.yaml
      namespace.yaml
  crossplane/
    kustomization.yaml           # references cluster-templates/<cloud>/<topology>/crossplane
    patches/
      ...                        # AWS: user, policy, policy-attachment, access-key
                                 # Azure: resource-group, application, service-principal,
                                 #        client-secret, role-assignment-*
```

## Cluster templates

The `cluster-templates/` directory contains shared base resources organized by cloud provider and topology:

```
cluster-templates/
  aws/      {standard,compact,sno}
  azure/    {standard,compact,sno}
  gcp/      {standard,compact,sno}   # templates only; no generator yet
```

## Adding a cloud provider

1. Add `cluster-templates/<cloud>/{standard,compact,sno}/{hive,crossplane}`.
2. Implement a `Provider` subclass in `src/scaffold/providers/<cloud>.py` (see `aws.py` and `azure.py`).
3. Replace the `PlannedProvider` entry in `src/scaffold/providers/__init__.py` with an instance of it.

## Validation

By default the tool runs `kustomize build` on both the `hive/` and `crossplane/` subdirectories after scaffolding. If validation fails the tool exits with code 1 and prints the kustomize error. Use `--skip-validation` to bypass this step (e.g. when kustomize is not installed or the cluster-templates bases are not present locally).

If the target cluster directory already exists, the tool refuses to overwrite it unless `--force` is passed.

## Development

### Running tests

```bash
pip install tox
tox
```

Or directly with pytest:

```bash
pip install pytest
pytest tests/ -v
```

### Linting

The project is configured for pylint and bandit (see `pyproject.toml` for rule settings).
