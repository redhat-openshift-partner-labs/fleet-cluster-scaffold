# fleet-cluster-scaffold

Standalone CLI tool for scaffolding OpenShift cluster overlay directories with Kustomize. Generates all the Hive and Crossplane resources needed to provision a cluster on AWS, without depending on the fleet monorepo.

## What it does

Given a cluster name, AWS region, and tier, `fleet-scaffold-cluster` generates a complete Kustomize overlay directory containing:

- **Hive resources** -- ClusterDeployment, MachinePool, ManagedCluster, KlusterletAddonConfig, install-config Secret, and Namespace patches
- **Crossplane resources** -- IAM User, Policy, UserPolicyAttachment, and AccessKey patches
- **Cluster metadata** -- optional metadata such as the htpasswd identity provider name

Each overlay references shared base resources in `cluster-templates/` via relative paths, so clusters stay lightweight while sharing common definitions.

## Requirements

- Python 3.11+
- [kustomize](https://kubectl.docs.kubernetes.io/installation/kustomize/) (for post-scaffold validation; skip with `--skip-validation`)

## Installation

```bash
pip install .
```

This installs the `fleet-scaffold-cluster` command.

## Usage

### Quick start

```bash
fleet-scaffold-cluster --name my-cluster --region us-east-1 --tier base
```

This creates `./my-cluster/` with the full Kustomize overlay structure and validates it with `kustomize build`.

### Required arguments

| Flag       | Description                        |
|------------|------------------------------------|
| `--name`   | Cluster name (must be a valid DNS-1123 label: lowercase alphanumeric and hyphens, 1-63 chars) |
| `--region` | AWS region (e.g. `us-east-1`)      |
| `--tier`   | Cluster tier: `base`, `virt`, `ai` |

### Optional arguments

| Flag                       | Default                      | Description                                                  |
|----------------------------|------------------------------|--------------------------------------------------------------|
| `--environment`            | `development`                | Environment label applied to ManagedCluster                  |
| `--profile`                | `aws/standard`               | Template profile (`aws/standard`, `aws/compact`, `aws/sno`)  |
| `--base-domain`            | `openshiftpartnerlabs.com`   | Cluster base DNS domain                                      |
| `--control-plane-type`     | `m7i.4xlarge`                | EC2 instance type for control plane nodes                    |
| `--worker-type`            | `m7i.2xlarge`                | EC2 instance type for worker nodes                           |
| `--control-plane-replicas` | `3`                          | Number of control plane replicas                             |
| `--worker-replicas`        | `3`                          | Number of worker replicas                                    |
| `--image-set`              | `img4.21.13-x86-64-appsub`  | OpenShift image set reference                                |
| `--zones`                  | `<region>a,b,c`              | Comma-separated availability zone list                       |
| `--htpasswd-provider-name` | *(none)*                     | Display name for the htpasswd identity provider              |
| `--base-path`              | `.`                          | Parent directory for the cluster overlay                     |
| `--cluster-templates-dir`  | `cluster-templates`          | Path to shared cluster templates directory                   |
| `--force`                  |                              | Overwrite an existing cluster directory                      |
| `--skip-validation`        |                              | Skip `kustomize build` validation after scaffolding          |

### Examples

Scaffold with defaults:

```bash
fleet-scaffold-cluster \
  --name dev-west-01 \
  --region us-west-2 \
  --tier base
```

Scaffold with all options:

```bash
fleet-scaffold-cluster \
  --name prod-east-01 \
  --region us-east-2 \
  --tier ai \
  --environment production \
  --profile aws/standard \
  --base-domain custom.example.com \
  --control-plane-type m7i.8xlarge \
  --worker-type m7i.4xlarge \
  --control-plane-replicas 5 \
  --worker-replicas 6 \
  --zones us-east-2a,us-east-2b \
  --htpasswd-provider-name "Acme Corp" \
  --force \
  --skip-validation
```

## Generated directory structure

```
<cluster-name>/
  kustomization.yaml            # aggregates hive/ and crossplane/
  metadata.yaml                 # cluster metadata (e.g. htpasswd provider name)
  hive/
    kustomization.yaml           # references cluster-templates/<profile>/hive base
    patches/
      clusterdeployment.yaml
      install-config.yaml
      install-config-meta.yaml
      klusterletaddonconfig.yaml
      machinepool-worker.yaml
      managedcluster.yaml
      namespace.yaml
  crossplane/
    kustomization.yaml           # references cluster-templates/<profile>/crossplane base
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
  aws/
    compact/
    sno/
    standard/        # default profile
```

Only AWS profiles are currently supported. Generated overlays reference these bases via relative paths in their `kustomization.yaml` files.

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
