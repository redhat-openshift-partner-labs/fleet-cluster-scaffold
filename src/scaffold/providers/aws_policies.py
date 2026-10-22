"""Cluster-scoped AWS IAM policies for the scoped (Manual credentials mode) workflow.

Every credential that reaches the spoke (per-operator IAM users, node roles) is limited to
resources owned by its cluster:

- instances: ec2:InstanceProfile must be one of the cluster's instance profiles
  (<infra ID>-{master,worker}-profile, matched exactly by infra_id_pattern; created by the installer from the BYO roles)
- volumes, snapshots, security groups, subnets, VPCs, load balancers: the ownership tag
  TAG_KEY=<cluster name>, applied by the installer (userTags) and propagated to operator-created
  resources (propagateUserTags)
- only create-time requests may set the ownership tag, so a spoke cannot claim a foreign
  resource by tagging it
- S3: buckets named <infra ID>-image-registry-*; Route53: records under *.apps.<cluster>.<domain>

The installer's infra ID and VPC are unknown until install, so policies carry
INFRA_ID_PLACEHOLDER / VPC_ID_PLACEHOLDER, which match nothing (fail closed) until the fleet
pipeline substitutes the real values after install. That enables a second ownership key,
kubernetes.io/cluster/<infraID>=owned, which machine-api, EBS CSI and the cloud-controller-manager
always apply at create time (so partner LoadBalancer Services need no annotation), and limits
egress-IP ENI changes to the cluster VPC.

Operator actions mirror the OCP 4.20/4.21 AWS CredentialsRequests
(`oc adm release extract --credentials-requests --cloud=aws --included`). Re-diff on every OCP
minor upgrade.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from scaffold.providers.base import CLUSTER_LABEL

# Same key as the hub ownership label, so one name identifies a cluster in AWS and on the hub
TAG_KEY = CLUSTER_LABEL

# Substituted post-install by the fleet pipeline (scope-aws-credentials task)
INFRA_ID_PLACEHOLDER = "INFRA_ID_PLACEHOLDER"
VPC_ID_PLACEHOLDER = "VPC_ID_PLACEHOLDER"
CLUSTER_TAG = f"kubernetes.io/cluster/{INFRA_ID_PLACEHOLDER}"

# installer: maxLen 27 - (randomLen 5 + 1); pkg/asset/installconfig/clusterid.go
_INFRA_BASE_MAX = 21


@dataclass(frozen=True)
class Component:
    """An OpenShift operator that needs AWS credentials in Manual mode."""

    key: str  # short name used in IAM/Crossplane resource names
    credentials_request: str
    namespace: str
    secret: str


COMPONENTS: tuple[Component, ...] = (
    Component("machine-api", "openshift-machine-api-aws", "openshift-machine-api", "aws-cloud-credentials"),
    Component("cco-iam-ro", "cloud-credential-operator-iam-ro", "openshift-cloud-credential-operator", "cloud-credential-operator-iam-ro-creds"),
    Component("image-registry", "openshift-image-registry", "openshift-image-registry", "installer-cloud-credentials"),
    Component("ingress", "openshift-ingress", "openshift-ingress-operator", "cloud-credentials"),
    Component("cncc", "openshift-cloud-network-config-controller-aws", "openshift-cloud-network-config-controller", "cloud-credentials"),
    Component("ebs-csi", "aws-ebs-csi-driver-operator", "openshift-cluster-csi-drivers", "ebs-cloud-credentials"),
)

# Longest IAM name suffix appended to the cluster name; IAM user/role names are capped at 64.
MAX_NAME_SUFFIX = max(len(f"-{c.key}") for c in COMPONENTS)
IAM_NAME_MAX = 64
MANAGED_POLICY_MAX = 6144  # operator users (managed policies)
INLINE_ROLE_POLICY_MAX = 10240  # node roles (inline policies)


def infra_prefix(cluster_name: str) -> str:
    """Base of the installer-generated infra ID (<base>-<5 random>), which prefixes cluster IAM/S3 names."""
    base = re.sub(r"[^A-Za-z0-9-]", "-", cluster_name)
    base = re.sub(r"-{2,}", "-", base)
    return base[:_INFRA_BASE_MAX].rstrip("-")


def infra_id_pattern(cluster_name: str) -> str:
    """IAM pattern matching exactly the installer infra ID (<prefix>-<5 random>; '?' is one character).

    A trailing '<prefix>-*' would also match a cluster whose name extends this one ('acme-2' for 'acme').
    """
    return f"{infra_prefix(cluster_name)}-?????"


def node_role_arns(cluster_name: str) -> list[str]:
    """The cluster's BYO node roles (install-config iamRole)."""
    return [f"arn:aws:iam::*:role/{cluster_name}-{role}-role" for role in ("master", "worker")]


def render(doc: dict[str, Any]) -> str:
    """Compact JSON; IAM managed-policy size limits count characters."""
    return json.dumps(doc, separators=(",", ":"))


def _doc(*statements: dict[str, Any]) -> dict[str, Any]:
    return {"Version": "2012-10-17", "Statement": list(statements)}


def _stmt(sid: str, actions: list[str], resources: str | list[str] = "*", condition: dict | None = None) -> dict[str, Any]:
    st: dict[str, Any] = {"Sid": sid, "Effect": "Allow", "Action": actions, "Resource": resources}
    if condition:
        st["Condition"] = condition
    return st


def _owned(sid: str, actions: list[str], resources: str | list[str], conditions: tuple[dict, dict],
           extra: dict | None = None) -> list[dict[str, Any]]:
    """One statement per ownership key; IAM ANDs keys within a condition, so OR needs two statements."""
    return [_stmt(f"{sid}{suffix}", actions, resources, {**(extra or {}), **cond})
            for suffix, cond in zip(("", "ByClusterTag"), conditions)]


def _ec2(resource: str) -> str:
    # images and snapshots have no account segment in their ARN
    account = "" if resource in ("image", "snapshot") else "*"
    return f"arn:aws:ec2:*:{account}:{resource}/*"


def _elb(resource: str) -> str:
    return f"arn:aws:elasticloadbalancing:*:*:{resource}/*"


class _Scope:
    """Per-cluster ARNs and conditions."""

    def __init__(self, name: str, region: str, base_domain: str) -> None:
        self.name = name
        self.region = region
        self.base_domain = base_domain
        self.roles = node_role_arns(name)
        self.own_profile = {"ArnLike": {"ec2:InstanceProfile": [
            f"arn:aws:iam::*:instance-profile/{infra_id_pattern(name)}-{role}-profile" for role in ("master", "worker")]}}
        self.ec2_owned = {"StringEquals": {f"ec2:ResourceTag/{TAG_KEY}": name}}
        # aws:ResourceTag: supported by both classic ELB and ELBv2 actions
        self.elb_owned = {"StringEquals": {f"aws:ResourceTag/{TAG_KEY}": name}}
        self.request_tag = {"StringEquals": {f"aws:RequestTag/{TAG_KEY}": name}}
        # Either ownership key: the scaffold tag, or the installer/operator cluster tag
        self.ec2_owned_any = (self.ec2_owned, {"StringEquals": {f"ec2:ResourceTag/{CLUSTER_TAG}": "owned"}})
        self.elb_owned_any = (self.elb_owned, {"StringEquals": {f"aws:ResourceTag/{CLUSTER_TAG}": "owned"}})
        self.request_tag_any = (self.request_tag, {"StringEquals": {f"aws:RequestTag/{CLUSTER_TAG}": "owned"}})
        self.own_vpc = {"ArnLike": {"ec2:Vpc": f"arn:aws:ec2:*:*:vpc/{VPC_ID_PLACEHOLDER}"}}

    def ec2_create_action(self, *actions: str) -> dict:
        return {"StringEquals": {"ec2:CreateAction": list(actions)}}

    def kms(self, sid: str) -> list[dict[str, Any]]:
        """KMS use only through EC2 (EBS encryption); grants only for AWS resources."""
        return [
            _stmt(f"{sid}KMSViaEC2", [
                "kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:GenerateDataKeyWithoutPlainText",
                "kms:ReEncrypt*", "kms:DescribeKey",
            ], condition={"StringEquals": {"kms:ViaService": f"ec2.{self.region}.amazonaws.com"}}),
            _stmt(f"{sid}KMSGrants", ["kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"],
                  condition={"Bool": {"kms:GrantIsForAWSResource": "true"}}),
        ]


# ===================== operator (component) policies =====================

def _machine_api(s: _Scope) -> dict:
    return _doc(
        _stmt("Read", [
            "ec2:DescribeAvailabilityZones", "ec2:DescribeDhcpOptions", "ec2:DescribeImages", "ec2:DescribeInstances",
            "ec2:DescribeInstanceTypes", "ec2:DescribeInternetGateways", "ec2:DescribeSecurityGroups",
            "ec2:DescribeRegions", "ec2:DescribeSubnets", "ec2:DescribeVpcs",
            "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTargetGroups",
            "elasticloadbalancing:DescribeTargetHealth",
        ]),
        # Launch only cluster-profile instances that carry the ownership tag...
        *_owned("RunOwnedInstance", ["ec2:RunInstances"], _ec2("instance"), s.request_tag_any, s.own_profile),
        # ...into the cluster's own subnets and security groups
        *_owned("RunInOwnedNetwork", ["ec2:RunInstances"], [_ec2("subnet"), _ec2("security-group")], s.ec2_owned_any),
        _stmt("RunSupporting", ["ec2:RunInstances"], [
            _ec2("image"), _ec2("volume"), _ec2("network-interface"), _ec2("key-pair"), _ec2("snapshot"),
            _ec2("launch-template"), _ec2("placement-group"),
        ]),
        _stmt("TerminateOwned", ["ec2:TerminateInstances"], _ec2("instance"), s.own_profile),
        _stmt("TagOnLaunch", ["ec2:CreateTags"], [_ec2("instance"), _ec2("volume"), _ec2("network-interface")],
              s.ec2_create_action("RunInstances")),
        _stmt("TagOwnedInstance", ["ec2:CreateTags"], _ec2("instance"), s.own_profile),
        _stmt("PassNodeRoles", ["iam:PassRole"], s.roles, {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}}),
        _stmt("SpotServiceLinkedRole", ["iam:CreateServiceLinkedRole"], "arn:aws:iam::*:role/aws-service-role/*",
              {"StringEquals": {"iam:AWSServiceName": "spot.amazonaws.com"}}),
        *_owned("RegisterOwnedLB", ["elasticloadbalancing:RegisterInstancesWithLoadBalancer"], _elb("loadbalancer"),
                s.elb_owned_any),
        *_owned("RegisterOwnedTargets", ["elasticloadbalancing:RegisterTargets", "elasticloadbalancing:DeregisterTargets"],
                _elb("targetgroup"), s.elb_owned_any),
        *s.kms("MachineAPI"),
    )


def _cco_iam_ro(s: _Scope) -> dict:
    # Exact operator users: '<name>-*' would also match other clusters' users and the hub-only installer
    users = [f"arn:aws:iam::*:user/{s.name}-{c.key}" for c in COMPONENTS]
    return _doc(_stmt("ReadClusterUsers", ["iam:GetUser", "iam:GetUserPolicy", "iam:ListAccessKeys"], users))


def _image_registry(s: _Scope) -> dict:
    # Operator bucket name: <infraID>-image-registry-<region>-<random>
    bucket = f"arn:aws:s3:::{infra_id_pattern(s.name)}-image-registry-*"
    return _doc(_stmt("ClusterBuckets", [
        "s3:CreateBucket", "s3:DeleteBucket", "s3:PutBucketTagging", "s3:GetBucketTagging",
        "s3:PutBucketPublicAccessBlock", "s3:GetBucketPublicAccessBlock", "s3:PutEncryptionConfiguration",
        "s3:GetEncryptionConfiguration", "s3:PutLifecycleConfiguration", "s3:GetLifecycleConfiguration",
        "s3:GetBucketLocation", "s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
        "s3:ListBucketMultipartUploads", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts",
    ], [bucket, f"{bucket}/*"]))


def _ingress(s: _Scope) -> dict:
    apps = f"apps.{s.name}.{s.base_domain}"
    return _doc(
        _stmt("Read", ["elasticloadbalancing:DescribeLoadBalancers", "route53:ListHostedZones",
                       "route53:ListTagsForResources", "tag:GetResources"]),
        # Any zone (public + installer-created private), but only the cluster's apps records
        _stmt("ClusterAppsRecords", ["route53:ChangeResourceRecordSets"], "arn:aws:route53:::hostedzone/*",
              {"ForAllValues:StringLike": {"route53:ChangeResourceRecordSetsNormalizedRecordNames": [f"*.{apps}", apps]}}),
    )


def _cncc(s: _Scope) -> dict:
    # Node ENIs carry no ownership tag (machine-api tags only instances and volumes), so egress-IP
    # changes are limited to the cluster VPC once the pipeline substitutes VPC_ID_PLACEHOLDER.
    return _doc(
        _stmt("Read", ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus", "ec2:DescribeInstanceTypes",
                       "ec2:DescribeSubnets", "ec2:DescribeNetworkInterfaces"]),
        _stmt("EgressIPs", ["ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses",
                            "ec2:AssignIpv6Addresses", "ec2:UnassignIpv6Addresses"], _ec2("network-interface"), s.own_vpc),
    )


def _ebs_csi(s: _Scope) -> dict:
    return _doc(
        _stmt("Read", ["ec2:DescribeInstances", "ec2:DescribeSnapshots", "ec2:DescribeTags", "ec2:DescribeVolumes",
                       "ec2:DescribeVolumesModifications", "ec2:DescribeAvailabilityZones"]),
        *_volume_statements(s, "CSI"),
        *_owned("CreateOwnedSnapshot", ["ec2:CreateSnapshot"], _ec2("snapshot"), s.request_tag_any),
        *_owned("SnapshotOwnedVolume", ["ec2:CreateSnapshot"], _ec2("volume"), s.ec2_owned_any),
        *_owned("ManageOwnedSnapshots", ["ec2:DeleteSnapshot", "ec2:EnableFastSnapshotRestores"], _ec2("snapshot"),
                s.ec2_owned_any),
        _stmt("TagOnCreate", ["ec2:CreateTags"], [_ec2("volume"), _ec2("snapshot")],
              s.ec2_create_action("CreateVolume", "CreateSnapshot")),
        *_owned("TagOwned", ["ec2:CreateTags", "ec2:DeleteTags"], [_ec2("volume"), _ec2("snapshot")], s.ec2_owned_any),
        *s.kms("CSI"),
    )


def _volume_statements(s: _Scope, sid: str) -> list[dict[str, Any]]:
    """EBS volume lifecycle, one statement per resource type (AttachVolume authorizes instance and volume)."""
    return [
        *_owned(f"{sid}CreateOwnedVolume", ["ec2:CreateVolume"], _ec2("volume"), s.request_tag_any),
        *_owned(f"{sid}VolumeFromOwnedSnapshot", ["ec2:CreateVolume"], _ec2("snapshot"), s.ec2_owned_any),
        *_owned(f"{sid}ManageOwnedVolumes", ["ec2:AttachVolume", "ec2:DetachVolume", "ec2:DeleteVolume", "ec2:ModifyVolume"],
                _ec2("volume"), s.ec2_owned_any),
        _stmt(f"{sid}AttachToOwnedInstances", ["ec2:AttachVolume", "ec2:DetachVolume"], _ec2("instance"), s.own_profile),
    ]


_COMPONENT_POLICIES = {
    "machine-api": _machine_api,
    "cco-iam-ro": _cco_iam_ro,
    "image-registry": _image_registry,
    "ingress": _ingress,
    "cncc": _cncc,
    "ebs-csi": _ebs_csi,
}


def component_policy(key: str, name: str, region: str, base_domain: str) -> dict:
    return _COMPONENT_POLICIES[key](_Scope(name, region, base_domain))


# ===================== node role policies =====================

def master_role_policy(name: str, region: str, base_domain: str) -> dict:
    """Control plane role; used by the AWS cloud-controller-manager (LBs, security groups)."""
    s = _Scope(name, region, base_domain)
    lb_resources = [_elb("loadbalancer"), _elb("targetgroup"), _elb("listener"), _elb("listener-rule")]
    return _doc(
        _stmt("Read", ["ec2:Describe*", "elasticloadbalancing:Describe*", "kms:DescribeKey"]),
        *_owned("CreateSGInOwnedVpc", ["ec2:CreateSecurityGroup"], _ec2("vpc"), s.ec2_owned_any),
        *_owned("CreateOwnedSG", ["ec2:CreateSecurityGroup"], _ec2("security-group"), s.request_tag_any),
        *_owned("ManageOwnedSG", ["ec2:AuthorizeSecurityGroupIngress", "ec2:RevokeSecurityGroupIngress", "ec2:DeleteSecurityGroup"],
                _ec2("security-group"), s.ec2_owned_any),
        _stmt("SGRules", ["ec2:AuthorizeSecurityGroupIngress"], _ec2("security-group-rule")),
        _stmt("ModifyOwnedInstance", ["ec2:ModifyInstanceAttribute"], _ec2("instance"), s.own_profile),
        *_owned("ModifyInstanceOwnedSGVolume", ["ec2:ModifyInstanceAttribute"], [_ec2("security-group"), _ec2("volume")],
                s.ec2_owned_any),
        *_volume_statements(s, "Node"),
        _stmt("TagOnCreate", ["ec2:CreateTags"], [_ec2("security-group"), _ec2("volume")],
              s.ec2_create_action("CreateSecurityGroup", "CreateVolume")),
        *_owned("TagOwned", ["ec2:CreateTags"], [_ec2("security-group"), _ec2("volume")], s.ec2_owned_any),
        *_owned("CreateOwnedLB", ["elasticloadbalancing:CreateLoadBalancer", "elasticloadbalancing:CreateTargetGroup"],
                [_elb("loadbalancer"), _elb("targetgroup")], s.request_tag_any),
        _stmt("ELBTagOnCreate", ["elasticloadbalancing:AddTags"], lb_resources,
              {"StringEquals": {"elasticloadbalancing:CreateAction": ["CreateLoadBalancer", "CreateTargetGroup", "CreateListener", "CreateRule"]}}),
        *_owned("ManageOwnedLB", [
            "elasticloadbalancing:AddTags", "elasticloadbalancing:AttachLoadBalancerToSubnets",
            "elasticloadbalancing:ApplySecurityGroupsToLoadBalancer", "elasticloadbalancing:CreateListener",
            "elasticloadbalancing:CreateLoadBalancerPolicy", "elasticloadbalancing:CreateLoadBalancerListeners",
            "elasticloadbalancing:ConfigureHealthCheck", "elasticloadbalancing:DeleteListener",
            "elasticloadbalancing:DeleteLoadBalancer", "elasticloadbalancing:DeleteLoadBalancerListeners",
            "elasticloadbalancing:DeleteTargetGroup", "elasticloadbalancing:DeregisterInstancesFromLoadBalancer",
            "elasticloadbalancing:DeregisterTargets", "elasticloadbalancing:DetachLoadBalancerFromSubnets",
            "elasticloadbalancing:ModifyListener", "elasticloadbalancing:ModifyLoadBalancerAttributes",
            "elasticloadbalancing:ModifyTargetGroup", "elasticloadbalancing:ModifyTargetGroupAttributes",
            "elasticloadbalancing:RegisterInstancesWithLoadBalancer", "elasticloadbalancing:RegisterTargets",
            "elasticloadbalancing:SetLoadBalancerPoliciesForBackendServer",
            "elasticloadbalancing:SetLoadBalancerPoliciesOfListener", "elasticloadbalancing:SetSecurityGroups",
        ], lb_resources, s.elb_owned_any),
    )


def worker_role_policy() -> dict:
    return _doc(_stmt("Read", ["ec2:DescribeInstances", "ec2:DescribeRegions"]))


NODE_ASSUME_ROLE_POLICY = _doc({
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole",
})


# ===================== installer policy (hub only) =====================

def installer_policy(name: str) -> dict:
    """Installer/destroy and hub cert-manager DNS-01. Never copied to the spoke in Manual mode.

    Network/compute stay broad (the installer creates the VPC); IAM is limited to the cluster's
    BYO roles and the instance profiles the installer wraps around them.
    """
    roles = node_role_arns(name)
    return _doc(
        _stmt("Infrastructure", ["ec2:*", "elasticloadbalancing:*", "route53:*", "s3:*", "tag:*", "servicequotas:*"]),
        _stmt("IAMRead", ["iam:GetUser", "iam:ListRoles", "iam:ListUsers", "iam:ListInstanceProfiles",
                          "iam:ListInstanceProfilesForRole", "iam:ListRoleTags", "iam:ListUserTags",
                          "iam:SimulatePrincipalPolicy"]),
        _stmt("ClusterRoles", ["iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies",
                               "iam:TagRole", "iam:UntagRole"], roles),
        _stmt("PassClusterRoles", ["iam:PassRole"], roles, {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}}),
        _stmt("ClusterInstanceProfiles", [
            "iam:CreateInstanceProfile", "iam:DeleteInstanceProfile", "iam:GetInstanceProfile",
            "iam:AddRoleToInstanceProfile", "iam:RemoveRoleFromInstanceProfile",
            "iam:TagInstanceProfile", "iam:UntagInstanceProfile",
        ], f"arn:aws:iam::*:instance-profile/{infra_id_pattern(name)}-*"),
    )
