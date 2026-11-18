# AWS operator policy maintenance

This guide describes how to keep the scoped operator policies in `src/scaffold/providers/aws_policies.py` in step with OpenShift releases, and records why some actions are withheld, for maintainers of this repository.

- What the policies grant and how they reach a cluster: [aws.md](aws.md).
- Release check that reports a gap: [README, Release check](../README.md#release-check).

## Contents

- [AWS OCP minor upgrade procedure](#aws-ocp-minor-upgrade-procedure)
- [AWS withheld operator actions](#aws-withheld-operator-actions)
- [Why ccoctl is not used](#why-ccoctl-is-not-used)

## AWS OCP minor upgrade procedure

1. Scaffold a cluster with the new `--image-set` and read the gap lines.
2. For each missing action, either grant it in `aws_policies.py` scoped to the cluster, or withhold it: add a `Withheld(reason=..., enable=...)` entry to `INTENTIONALLY_DROPPED` and an entry to [AWS withheld operator actions](#aws-withheld-operator-actions). Repeat until the check passes.
3. Add the fixtures:

   ```bash
   oc adm release extract --credentials-requests --cloud=aws --included \
     --install-config=<install-config.yaml> \
     --to tests/fixtures/credentialsrequests/aws-<minor> <release image>
   ```

   `<install-config.yaml>` is the text under `stringData` in `hive/patches/install-config.yaml` of a scaffolded overlay. `tests/unit/test_aws_policies.py` checks coverage against every `aws-*` directory. Keep an older directory while clusters still use that release.
4. Set `cloudcredential.openshift.io/upgradeable-to` on the spoke.

## AWS withheld operator actions

These actions appear in the release's CredentialsRequests but are not granted. They are listed in `INTENTIONALLY_DROPPED` in `src/scaffold/providers/aws_policies.py`, where each entry carries a `reason` and an `enable` field. The release check skips them. If the operator calls one, the call fails with `UnauthorizedOperation`.

| Operator (CredentialsRequest) | Action | Since | Feature that fails |
|---|---|---|---|
| ingress (`openshift-ingress`) | `sts:AssumeRole` | 4.21 or earlier | Publishing DNS through a shared-VPC `hostedZoneRole` |
| machine-api (`openshift-machine-api-aws`) | `ec2:AllocateHosts` | 4.22 | MachineSets that place instances on EC2 Dedicated Hosts |
| machine-api (`openshift-machine-api-aws`) | `ec2:ReleaseHosts` | 4.22 | Same as `ec2:AllocateHosts` |
| ebs-csi (`aws-ebs-csi-driver-operator`) | `ec2:CopyVolumes` | 5.0 | PVC-to-PVC cloning. Nothing fails on 5.0.1. |
| ebs-csi (`aws-ebs-csi-driver-operator`) | `ec2:LockSnapshot` | 5.0 | Snapshot locking. Nothing fails on 5.0.1. |

Reason and grant condition for each action:

**`sts:AssumeRole`** (ingress)

- **Why it is withheld:** Fleet clusters do not use a shared VPC.
- **When and how to grant it:** If clusters move to a shared VPC: grant it on the one `hostedZoneRole` ARN only.

**`ec2:AllocateHosts`** (machine-api)

- **Why it is withheld:** It creates Dedicated Hosts, which are billed per host-hour while allocated and drawn from the account-wide host quota.
- **When and how to grant it:** When partners need Dedicated Hosts and fleet teardown releases hosts: grant it on `dedicated-host/*` only when the request carries the ownership tag, and add `AllocateHosts` to `TagOnLaunch`'s `ec2:CreateAction`.
- **Tagging:** machine-api in OCP 4.22.22 and 5.0.1 sends the ownership tag in the `AllocateHosts` request. `buildTagList` in `pkg/actuators/machine/instances.go` of openshift/machine-api-provider-aws adds the Infrastructure resource tags, which hold the install-config `userTags`.

**`ec2:ReleaseHosts`** (machine-api)

- **Why it is withheld:** Only needed together with `ec2:AllocateHosts`.
- **When and how to grant it:** Together with `ec2:AllocateHosts`: grant it on `dedicated-host/*` owned by the cluster.

**`ec2:CopyVolumes`** (ebs-csi)

- **Effect on 5.0.1:** None. The EBS CSI driver in OCP 5.0.1 (v1.48.0) does not implement volume cloning and does not call this action. Restoring from snapshots works.
- **Why it is withheld:** The source and the copy are both `volume` resources, and `aws:RequestTag` applies to the whole request. A statement allowing a copy tagged for this cluster therefore also matches a foreign source volume. Any volume in the account could be cloned, attached and read.
- **When and how to grant it:** Only once a condition provably limits the source to the cluster's own volumes, verified with a real `CopyVolumes` call in a sandbox account. The policy simulator is not enough.

**`ec2:LockSnapshot`** (ebs-csi)

- **Effect on 5.0.1:** None. The EBS CSI driver in OCP 5.0.1 (v1.48.0) does not implement snapshot locking and does not call this action.
- **Why it is withheld:** After the cooling-off period, no one can remove or shorten a compliance-mode lock, including the account root. Locks last up to 36,500 days. The snapshot blocks teardown and keeps billing until the lock expires or the account is closed.
- **When and how to grant it:** Only if a condition can restrict locks to governance mode or a short duration, for both `LockDuration` and `ExpirationDate` requests. Scope it to the cluster's own snapshots.

The release check does not report when a later EBS CSI driver starts calling `ec2:CopyVolumes` or `ec2:LockSnapshot`, because the 5.0 CredentialsRequest already lists both. On each OCP upgrade, check whether the driver advertises the CSI `CLONE_VOLUME` capability in `pkg/driver/controller.go`. `oc adm release info <release image> --commits` prints the driver's source repository and commit on the `aws-ebs-csi-driver` line.

## Why ccoctl is not used

`ccoctl` is the OpenShift tool that creates the operator IAM roles for an AWS STS cluster from the release's CredentialsRequests. The scaffold renders its own policies and has Crossplane create the IAM resources, for these reasons:

- **The default `ccoctl` policies are account-wide.** `ccoctl aws create-iam-roles` copies each CredentialsRequest statement into the role policy. Every statement in the 4.21 requests has `resource: '*'`. One cluster's machine-api credential could then terminate another cluster's instances, which breaks the isolation rule in [AWS credentials](aws.md#aws-credentials-cluster-scoped-default).
- **Narrowed CredentialsRequests would give the same isolation at a higher cost.** `ccoctl` passes a narrowed `resource` and a `policyCondition` through to the role policy, so it could deliver the policies in `aws_policies.py`. The permissions would be identical. A statement accepts one `resource` string, so each multi-resource statement would have to be split. IAM creation would move from Crossplane reconciliation to a pipeline step that holds IAM and S3 write credentials.
- **STS changes the credential type and leaves the permissions unchanged.** The roles `ccoctl` creates are assumed with a service account token (`sts:AssumeRoleWithWebIdentity`). A cluster-admin can request a token for any operator service account, so a partner reaches the same policies as with the per-operator IAM users.
- **STS adds a per-cluster OIDC issuer to protect.** Its key document must be publicly readable. A principal that can replace the document can assume every operator role of that cluster. Teardown must delete the IAM OIDC provider and the roles together with the issuer bucket.

Costs of the current design:

- The operators use long-lived IAM user access keys. STS credentials expire after about an hour. If short-lived credentials become a requirement, Crossplane can create the OIDC provider and the roles with the same scoped policies.
- The custom policies are outside Red Hat's tested configuration; see [AWS limits and residuals](aws.md#aws-limits-and-residuals).
