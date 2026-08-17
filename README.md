# fleet-cluster-scaffold

Standalone CLI tool for scaffolding OpenShift cluster overlay directories with Kustomize. Generates all the Hive and Crossplane resources needed to provision a cluster on AWS, without depending on the fleet monorepo.

## What it does

Given a cluster name, AWS region, and tier, `fleet-scaffold-cluster` generates a complete Kustomize overlay directory containing:

- **Hive resources** -- ClusterDeployment, MachinePool, ManagedCluster, KlusterletAddonConfig, install-config Secret, and Namespace patches
- **Crossplane resources** -- IAM User, Policy, UserPolicyAttachment, and AccessKey patches

Each overlay references shared base resources in `cluster-templates/` via relative paths, so clusters stay lightweight while sharing common definitions.

## Requirements

- Python 3.11+
- [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/) (for post-scaffold validation; optional with `--skip-validation`)

## Installation

```bash
pip install .
```

This installs the `fleet-scaffold-cluster` command.

## Usage

```bash
fleet-scaffold-cluster --name my-cluster --region us-east-1 --tier base
```

This creates `./my-cluster/` with the full Kustomize overlay structure and validates it with `kustomize build`.

### Required arguments

| Flag       | Description                        |
|------------|------------------------------------|
| `--name`   | Cluster name                       |
| `--region` | AWS region (e.g. `us-east-1`)      |
| `--tier`   | Cluster tier: `base`, `virt`, `ai` |

### Optional arguments

| Flag                       | Default                      | Description                                |
|----------------------------|------------------------------|--------------------------------------------|
| `--environment`            | `development`                | Environment label                          |
| `--control-plane-type`     | `m7i.4xlarge`                | EC2 instance type for control plane nodes  |
| `--worker-type`            | `m7i.2xlarge`                | EC2 instance type for worker nodes         |
| `--control-plane-replicas` | `3`                          | Number of control plane replicas           |
| `--worker-replicas`        | `3`                          | Number of worker replicas                  |
| `--image-set`              | `img4.21.13-x86-64-appsub`  | OpenShift image set reference              |
| `--zones`                  | `<region>a,b,c`              | Comma-separated availability zone list     |
| `--base-path`              | `.`                          | Parent directory for the cluster overlay    |
| `--profile`                | `aws/standard`               | Template profile directory (e.g. `aws/standard`, `aws-ha`) |
| `--base-domain`            | `openshiftpartnerlabs.com`   | Cluster base DNS domain override           |
| `--htpasswd-provider-name` | (none)                       | Display name for the htpasswd identity provider |
| `--cluster-templates-dir`  | `cluster-templates`          | Path to shared cluster templates           |
| `--force`                  | `false`                      | Overwrite existing cluster directory       |
| `--skip-validation`        | `false`                      | Skip `kustomize build` validation          |

### Example: custom cluster

```bash
fleet-scaffold-cluster \
  --name prod-east-01 \
  --region us-east-2 \
  --tier virt \
  --environment production \
  --control-plane-replicas 3 \
  --worker-replicas 5 \
  --worker-type m7i.4xlarge \
  --zones us-east-2a,us-east-2b,us-east-2c
```

## Generated directory structure

```
<cluster-name>/
  kustomization.yaml          # aggregates hive/ and crossplane/
  hive/
    kustomization.yaml         # references cluster-templates base
    patches/
      clusterdeployment.yaml
      install-config.yaml
      install-config-meta.yaml
      klusterletaddonconfig.yaml
      machinepool-worker.yaml
      managedcluster.yaml
      namespace.yaml
  crossplane/
    kustomization.yaml         # references cluster-templates base
    patches/
      access-key.yaml
      policy-attachment.yaml
      policy.yaml
      user.yaml
```

## Cluster templates

The `cluster-templates/` directory contains shared base resources organized by cloud provider and topology:

```
cluster-templates/
  aws/          # compact, sno, standard
  aws-ha/       # HA configuration
```

Only AWS profiles are currently supported. Generated overlays reference these bases via relative paths in their `kustomization.yaml` files.

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
