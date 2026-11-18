# fleet-cluster-scaffold

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](#requirements)
[![Kustomize](https://img.shields.io/badge/Kustomize-required-326CE5?logo=kubernetes&logoColor=white)](#requirements)
[![AWS](https://img.shields.io/badge/AWS-supported-232F3E?logo=amazonwebservices&logoColor=white)](#aws)
[![Azure](https://img.shields.io/badge/Azure-not%20ready-0078D4?logo=microsoftazure&logoColor=white)](docs/azure.md#azure-status)

`fleet-cluster-scaffold` is a command-line tool that generates the Kustomize overlay directory for one OpenShift cluster on AWS or Azure, for engineers who provision clusters through the fleet pipelines. The overlay holds the Hive and Crossplane resources for the cluster. The tool runs without the fleet monorepo.

## Contents

- [Overview](#overview)
  - [Provider status](#provider-status)
- [Getting started](#getting-started)
  - [Requirements](#requirements)
  - [Installation](#installation)
  - [Quick start](#quick-start)
- [Command reference](#command-reference)
  - [Command syntax](#command-syntax)
  - [Common arguments (all clouds)](#common-arguments-all-clouds)
- [Provider guides](#provider-guides)
  - [AWS](#aws): flags and example. Guides: [docs/aws.md](docs/aws.md), [docs/aws-policy-maintenance.md](docs/aws-policy-maintenance.md)
  - [Azure](#azure): flags and example. Guide: [docs/azure.md](docs/azure.md)
- [Generated output](#generated-output)
- [Templates and extension](#templates-and-extension)
  - [Cluster templates](#cluster-templates)
  - [Adding a cloud provider](#adding-a-cloud-provider)
- [Validation](#validation)
  - [Release check](#release-check)
- [Development](#development)
  - [Running tests](#running-tests)
  - [Linting](#linting)

## Overview

Given a cloud, cluster name, region, and tier, `fleet-scaffold-cluster` generates a complete Kustomize overlay directory containing:

- **Hive resources:** ClusterDeployment, MachinePool, ManagedCluster, KlusterletAddonConfig, install-config Secret, and Namespace patches
- **Crossplane resources:** per-cluster cloud credentials
  - AWS: installer IAM user, cluster-scoped IAM users for each OpenShift operator, and BYO node roles
  - Azure: ResourceGroup, Entra Application, ServicePrincipal, client secret, and RoleAssignments
- **Cluster metadata:** `platform` and cloud-specific keys read by the fleet pipelines, plus optional values such as the htpasswd identity provider name

Each overlay references shared base resources in `cluster-templates/<cloud>/<topology>/` via relative paths, so clusters stay lightweight while sharing common definitions.

Every generated resource carries the label `openshiftpartnerlabs.com/cluster=<name>`. The Crossplane managed resources are cluster-scoped, so deleting the cluster namespace does not remove them. Teardown should select them by this label (for example `oc get managed -l openshiftpartnerlabs.com/cluster=<name>`) instead of a hard-coded name list.

### Provider status

| Cloud      | Status       | Notes |
|------------|--------------|-------|
| `aws`      | Supported    | Cluster-scoped IAM workflow |
| `azure`    | Not ready    | Overlay generation only; see [Azure status](docs/azure.md#azure-status) |
| `gcp`      | Planned      | Command exits `1` |
| `ibmcloud` | Planned      | Command exits `1` |

## Getting started

### Requirements

- Python 3.11+
- [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/) (for post-scaffold validation; skip with `--skip-validation`)
- [oc](https://mirror.openshift.com/pub/openshift-v4/clients/ocp/) and network access to `quay.io` (for the [release check](#release-check) of scoped AWS clusters; not needed with `--credentials-requests-dir` or `--skip-release-check`)

### Installation

```bash
pip install .
```

This installs the `fleet-scaffold-cluster` command. `pip install .` installs a copy of the source, so run it again after pulling changes.

Print the installed version:

```bash
fleet-scaffold-cluster --version
```

Expected output: `fleet-scaffold-cluster <version>`, where `<version>` is the `version` in `pyproject.toml` at install time. An editable install (`pip install -e .`) keeps reporting the version it was installed with until it is reinstalled.

### Quick start

```bash
# AWS
fleet-scaffold-cluster aws --name my-cluster --region us-east-1 --tier base

# Azure
fleet-scaffold-cluster azure --name my-cluster --region eastus2 --tier base \
  --subscription-id 00000000-0000-0000-0000-000000000000
```

The AWS command creates `./my-cluster/` (see [Generated output](#generated-output)), exits `0` and prints:

```text
Scaffolding aws/standard cluster 'my-cluster' in ./
  -> wrote ./my-cluster
  -> hive: OK
  -> crossplane: OK
  -> release check:
  -> -> extracting CredentialsRequests from quay.io/openshift-release-dev/ocp-release:4.21.13-x86_64
  -> -> (oc adm release extract, up to 300s)
  -> -> Release check: 6 CredentialsRequests from quay.io/openshift-release-dev/ocp-release:4.21.13-x86_64 covered by the scoped policies.
  -> -> Cluster 'my-cluster' scaffolded successfully
```

| Output lines | Step | Details |
|---|---|---|
| `hive: OK`, `crossplane: OK` | `kustomize build` of each subdirectory | [Validation](#validation) |
| `release check:` and the lines after it | For AWS clusters with scoped credentials (the default): the operator policies are verified against the CredentialsRequests of the release behind `--image-set`. This needs `oc`, access to `quay.io`, and about 20 seconds. | [Release check](#release-check) |

## Command reference

### Command syntax

```text
fleet-scaffold-cluster CLOUD --name NAME --region REGION --tier TIER [options]
fleet-scaffold-cluster --version
```

Run `fleet-scaffold-cluster CLOUD --help` for the full flag list of a cloud. `--version` prints the installed version and exits `0`; it takes no `CLOUD`.

### Common arguments (all clouds)

| Flag                       | Default                      | Description                                                  |
|----------------------------|------------------------------|--------------------------------------------------------------|
| `--name`                   | *(required)*                 | Cluster name (valid DNS-1123 label: lowercase alphanumeric and hyphens, 1-63 chars; at most 49 for AWS scoped credentials) |
| `--region`                 | *(required)*                 | Cloud region (e.g. `us-east-1`, `eastus2`)                   |
| `--tier`                   | *(required)*                 | Cluster tier: `base`, `virt`, `ai`                           |
| `--topology`               | `standard`                   | `standard`, `compact`, or `sno`; selects `cluster-templates/<cloud>/<topology>` |
| `--environment`            | `development`                | Environment label applied to ManagedCluster                  |
| `--base-domain`            | `openshiftpartnerlabs.com`   | Cluster base DNS domain                                      |
| `--control-plane-type`     | cloud-specific               | Instance type for control plane nodes                        |
| `--worker-type`            | cloud-specific               | Instance type for worker nodes                               |
| `--control-plane-replicas` | topology-specific            | `3` (standard, compact) or `1` (sno)                         |
| `--worker-replicas`        | topology-specific            | `3` (standard) or `0` (compact, sno; must stay `0`, they have no worker MachinePool) |
| `--image-set`              | `img4.21.13-x86-64-appsub`   | OpenShift ClusterImageSet name                               |
| `--zones`                  | cloud-specific               | Comma-separated zone list                                    |
| `--install-attempts-limit` | `1`                          | Hive install attempts before the ClusterDeployment fails; failed installs need a human retrigger |
| `--htpasswd-provider-name` | *(none)*                     | Display name for the htpasswd identity provider              |
| `--ai-accelerator`         | *(none)*                     | `none` for CPU-only OpenShift AI or `nvidia-gpu` for GPU-backed OpenShift AI; requires `--tier ai` |
| `--base-path`              | `.`                          | Parent directory for the cluster overlay                     |
| `--cluster-templates-dir`  | `cluster-templates`          | Path to shared cluster templates directory                   |
| `--force`                  |                              | Overwrite an existing cluster directory                      |
| `--skip-validation`        |                              | Skip `kustomize build` validation after scaffolding          |
| `--release-image`          | derived from `--image-set`   | Release image whose CredentialsRequests the scoped AWS policies are checked against ([release check](#release-check)) |
| `--credentials-requests-dir` | *(none)*                   | Check against CredentialsRequest manifests already extracted into this directory instead of pulling the release image |
| `--skip-release-check`     |                              | Scaffold without the release check; the scoped policies are then unverified for that release |

## Provider guides

### AWS

| Setting                     | Default                  |
|-----------------------------|--------------------------|
| `--control-plane-type`      | `m7i.4xlarge`            |
| `--worker-type`             | `m7i.2xlarge`            |
| `--zones`                   | `<region>a,b,c`          |
| `--legacy-mint-credentials` | off (rollback only; see [AWS legacy Mint mode](docs/aws.md#aws-legacy-mint-mode-rollback-only)) |

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

New AWS clusters use cluster-scoped credentials: `credentialsMode: Manual`, one IAM user per OpenShift operator, and BYO node roles. No credential that reaches a spoke may act on another cluster's resources.

| Guide | Content | Reader |
|---|---|---|
| [docs/aws.md](docs/aws.md) | Scoped credentials, fleet pipeline contract, hub prerequisites, limits and residuals, legacy Mint mode | Engineers who operate the hub and the pipelines |
| [docs/aws-policy-maintenance.md](docs/aws-policy-maintenance.md) | OCP minor upgrade procedure, withheld operator actions, why `ccoctl` is not used | Maintainers of `aws_policies.py` |

### Azure

> [!WARNING]
> Do not use Azure overlays for partner clusters. The installer credentials reach the spoke, where a partner with cluster-admin can change other clusters' DNS records. See [Azure status](docs/azure.md#azure-status).

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

[docs/azure.md](docs/azure.md) covers the Azure status, the credential flow and the hub prerequisites, for engineers who evaluate or extend Azure support.

## Generated output

```
<cluster-name>/
  kustomization.yaml            # aggregates hive/ and crossplane/
  metadata.yaml                 # platform, cloud-specific pipeline keys, htpasswd provider name
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
    kustomization.yaml           # references cluster-templates/<cloud>/<topology>/crossplane[-scoped]
    patches/
      ...                        # AWS scoped: installer/, node-roles/, <operator>/
                                 # AWS legacy: user, policy, policy-attachment, access-key
                                 # Azure: resource-group, application, service-principal,
                                 #        client-secret, role-assignment-*
```

## Templates and extension

### Cluster templates

The `cluster-templates/` directory contains shared base resources organized by cloud provider and topology:

```
cluster-templates/
  aws/      {standard,compact,sno}/{hive,crossplane-scoped,crossplane}   # crossplane/ = legacy Mint mode
  azure/    {standard,compact,sno}
  gcp/      {standard,compact,sno}   # templates only; no generator yet
```

### Adding a cloud provider

1. Add `cluster-templates/<cloud>/{standard,compact,sno}/{hive,crossplane}`.
2. Implement a `Provider` subclass in `src/scaffold/providers/<cloud>.py` (see `aws.py` and `azure.py`).
3. Replace the `PlannedProvider` entry in `src/scaffold/providers/__init__.py` with an instance of it.

## Validation

By default the tool runs `kustomize build` on both the `hive/` and `crossplane/` subdirectories after scaffolding. If validation fails the tool exits with code 1 and prints the kustomize error. Use `--skip-validation` to bypass this step (e.g. when kustomize is not installed or the cluster-templates bases are not present locally).

Validation also fails if any base-template name (`cluster-placeholder*`, `subscription-placeholder`) survives the build. That means a patch matched nothing, usually because `--cluster-templates-dir` points at stale templates; kustomize itself does not report this. The pipeline-bound placeholders (`INFRA_ID_PLACEHOLDER`, `VPC_ID_PLACEHOLDER`, `principal-id-placeholder`) are expected.

If the target cluster directory already exists, the tool refuses to overwrite it unless `--force` is passed.

### Release check

For AWS clusters with scoped credentials (the default) the scaffold verifies the operator policies in `aws_policies.py` against the CredentialsRequests of the OpenShift release after `kustomize build`:

1. The release image is derived from `--image-set` by naming convention: `img<version>-x86-64-appsub` maps to `quay.io/openshift-release-dev/ocp-release:<version>-x86_64`. The scaffold does not read the hub's ClusterImageSet, so when `spec.releaseImage` differs from the convention pass `--release-image PULLSPEC`. An image-set name outside the convention fails the check.
2. `oc adm release extract --credentials-requests --cloud=aws --included --install-config=<rendered install-config>` extracts the CredentialsRequests the installer would apply for this cluster. The repository is public; no pull secret is used. This takes about 20 seconds; the log announces it with `-> release check:` followed by `-> -> extracting CredentialsRequests from <image>` and `-> -> (oc adm release extract, up to 300s)`, and prints nothing else until `oc` returns.
3. The requests are compared with `COMPONENTS` and the rendered policies: every AWS CredentialsRequest needs a scoped policy, every `COMPONENTS` entry must exist in the release, each operator's target Secret (namespace and name) must match, and every requested action must be granted (IAM wildcards in the policy match; actions in `INTENTIONALLY_DROPPED` are skipped, see [AWS withheld operator actions](docs/aws-policy-maintenance.md#aws-withheld-operator-actions)).

On success the log shows `-> -> Release check: <n> CredentialsRequests from <source> covered by the scoped policies.` followed by `-> -> Cluster '<name>' scaffolded successfully`. On any difference the command exits `1` with one line per gap, for example `ebs-csi lacks ec2:DescribeVolumeStatus`. The overlay has already been written at that point; fix `aws_policies.py`, refresh the fixtures (see [AWS OCP minor upgrade procedure](docs/aws-policy-maintenance.md#aws-ocp-minor-upgrade-procedure)) and regenerate the overlay with `--force`.

Flags:
- `--release-image PULLSPEC`: check against this release instead of the one derived from `--image-set`.
- `--credentials-requests-dir DIR`: check against manifests already extracted into `DIR` (offline runs, CI, fixture refresh); `oc` is not needed.
- `--skip-release-check`: skip the check. The scoped policies are then unverified for that release. Not for normal use.

The check is reported as not applicable for `--legacy-mint-credentials` and for Azure, which have no scoped policies. It runs even with `--skip-validation`.

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

The tests never run `oc`: the CLI tests patch the extraction and compare against `tests/fixtures/credentialsrequests/aws-4.21`. To scaffold without `oc` or network access, pass `--credentials-requests-dir tests/fixtures/credentialsrequests/aws-4.21` (or `aws-5.0` with `--image-set img5.0.1-x86-64-appsub`).

### Linting

The project is configured for pylint and bandit (see `pyproject.toml` for rule settings).
