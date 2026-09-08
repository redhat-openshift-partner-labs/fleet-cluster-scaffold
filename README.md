# fleet-cluster-scaffold

Standalone CLI tool for scaffolding OpenShift cluster overlay directories with Kustomize. Generates all the Hive and Crossplane resources needed to provision a cluster on AWS, without depending on the fleet monorepo.

## What it does

Given a cluster name, AWS region, and tier, `fleet-scaffold-cluster` generates a complete Kustomize overlay directory containing:

- **Hive resources** -- ClusterDeployment, profile-dependent MachinePool, ManagedCluster, KlusterletAddonConfig, install-config Secret, and Namespace patches
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
| `--control-plane-replicas` | Profile install count | Fixed by profile; explicit matching values accepted |
| `--worker-replicas`        | Profile install count | Fixed by profile; explicit matching values accepted |
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
  --control-plane-replicas 3 \
  --worker-replicas 3 \
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
      machinepool-worker.yaml   # standard only
      managedcluster.yaml
      namespace.yaml
  post-install/                 # compact only; excluded from root aggregation
    kustomization.yaml           # references shared compact/post-install base
    patches/
      machinepool-worker.yaml    # one worker, for application after readiness
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
      hive/         # install: one control-plane node, zero workers
      crossplane/
      post-install/ # shared worker MachinePool base
    sno/
    standard/        # default profile
```

Only AWS profiles are currently supported. Generated overlays reference these bases via relative paths in their `kustomization.yaml` files.

## Topology and compact handoff

| Profile | Install control-plane | Install workers | Desired topology after readiness |
|---------|----------------------:|----------------:|----------------------------------|
| `aws/sno` | 1 | 0 | 1 control-plane node, no workers |
| `aws/compact` | 1 | 0 | 1 control-plane node, 1 worker |
| `aws/standard` | 3 | 3 | 3 control-plane nodes, 3 workers |

Replica counts are fixed by profile. Omitted flags use the install counts above;
explicit matching values are accepted and conflicting overrides are rejected.
Tier (`base`, `virt`, or `ai`) does not change topology. Any nonblank instance type
and any nonempty zone list are accepted without querying AWS or checking type/zone
availability. CLI zone entries are trimmed, empty entries are rejected, and order
is preserved. The default zone list remains `<region>a`, `<region>b`, `<region>c`
for every profile.

Generate compact installation and handoff manifests together:

```bash
fleet-scaffold-cluster --name compact-01 --region us-east-1 --tier base \
  --profile aws/compact --control-plane-replicas 1 --worker-replicas 0
kustomize build compact-01/
kustomize build compact-01/post-install/
```

Compact's root and `hive/` entry points retain zero install workers and contain no
worker MachinePool. Its independent `post-install/` entry point renders only a
one-replica worker MachinePool with the cluster reference, selected worker type,
and zones. It references the shared `cluster-templates/aws/compact/post-install/`
base and does not re-emit the install-config Secret or Crossplane resources.
The separate installing project owns readiness checks and application of this
handoff. Generating or rendering these manifests does not activate them. SNO has
no worker MachinePool or post-install entry point.

## Validation

Configuration is validated with Pydantic before writing output. Invalid names,
unsupported profiles/tiers, conflicting replicas, blank instance types, and
malformed zones produce option-specific errors and exit code 1 without a traceback.
Argparse syntax errors, such as non-integer replica arguments, retain exit code 2.
Template directories and required Kustomize entry points must exist.

By default the tool runs `kustomize build` on the root, `hive/`, `crossplane/`, and,
for compact, `post-install/` entry points. Rendering failures exit with code 1.
`--skip-validation` skips only these builds; configuration and template checks
still run. Rendering verifies composition, not installation or readiness.

Existing cluster directories require `--force` to overwrite. Invalid configuration
leaves existing output untouched even with `--force`. Switching profiles removes
obsolete generated worker patches and the generated post-install entry point.

### Python library migration

`scaffold.lib.ClusterParams` remains available and re-exports
`scaffold.models.ClusterParams`. Construction now uses keyword arguments and raises
Pydantic `ValidationError` (a `ValueError` subclass) for invalid configuration.
Unknown fields are forbidden. Replica inputs must be nonnegative integers;
booleans, strings, floats, and explicit `None` are rejected. Omit replica fields to
resolve profile defaults. The former permissive dataclass accepted these inputs
and arbitrary replica overrides; callers must update accordingly.

Field names and attribute access are retained. Zones remain a list, with omitted
zones or `zones=None` resolving region defaults. Instances prevent field assignment;
treat the nested zones list as read-only too. Use `model_dump()` instead of
`dataclasses.asdict()` and construct a new validated instance when changing inputs.
Pydantic's `model_copy(update=...)` does not validate updates and should not be used
for unvalidated configuration. Manifest serialization continues to use PyYAML.

## Development

### Running tests

```bash
pip install tox
tox
```

Tox checks Python 3.11–3.14. To check only installed interpreters, use
`tox --skip-missing-interpreters`. The composition tests run real Kustomize builds
when `kustomize` is on PATH and report skips otherwise.

Or directly with pytest:

```bash
pip install pytest
python -m pytest tests/ -v
```

### Linting

The project is configured for pylint and bandit (see `pyproject.toml` for rule settings).
