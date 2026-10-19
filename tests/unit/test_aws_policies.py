"""Security invariants and CredentialsRequest coverage for the scoped AWS policies."""

import fnmatch
import json
import pathlib

import pytest
import yaml

from scaffold.providers import aws_policies as pol

NAME, REGION, DOMAIN = "10f25620-vscopeocpv", "us-east-2", "openshiftpartnerlabs.com"
PREFIX = pol.infra_prefix(NAME)
FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "credentialsrequests" / "aws-4.21"

# Actions deliberately not granted, with the reason
INTENTIONALLY_DROPPED = {
    "openshift-ingress": {"sts:AssumeRole"},  # only for shared-VPC hostedZoneRole, which fleet doesn't use
}
# Mutating action verbs that must never be allowed account-wide on the spoke
MUTATING = ("Terminate", "Delete", "Detach", "Attach", "Modify", "Revoke", "Authorize", "Deregister",
            "Register", "Set", "Put", "Create", "Run", "Assign", "Unassign", "Change", "Pass", "Enable",
            "Apply", "Configure", "Add", "Remove", "Release", "Allocate", "Encrypt", "Decrypt", "Generate",
            "ReEncrypt", "Abort")


def _credentials_requests() -> dict[str, list[str]]:
    out = {}
    for f in sorted(FIXTURES.glob("*.yaml")):
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                out[d["metadata"]["name"]] = [a for st in d["spec"]["providerSpec"]["statementEntries"] for a in st["action"]]
    return out


def _statements(doc: dict) -> list[dict]:
    return doc["Statement"]


def _as_list(v) -> list:
    return v if isinstance(v, list) else [v]


def _allowed_actions(doc: dict) -> set[str]:
    return {a for st in _statements(doc) if st["Effect"] == "Allow" for a in _as_list(st["Action"])}


def _spoke_policies() -> dict[str, dict]:
    """Every policy whose credential can reach the spoke (operator users and node roles)."""
    docs = {c.key: pol.component_policy(c.key, NAME, REGION, DOMAIN) for c in pol.COMPONENTS}
    docs["master-role"] = pol.master_role_policy(NAME, REGION, DOMAIN)
    docs["worker-role"] = pol.worker_role_policy()
    return docs


class TestInfraPrefix:
    @pytest.mark.parametrize("name,expected", [
        ("10f25620-vscopeocpv", "10f25620-vscopeocpv"),
        ("a" * 30, "a" * 21),
        ("abcdefghijklmnopqrst-uvw", "abcdefghijklmnopqrst"),  # cut lands on '-', trimmed
        ("a--b", "a-b"),
    ])
    def test_matches_installer_infra_id_base(self, name, expected):
        assert pol.infra_prefix(name) == expected


class TestCredentialsRequestCoverage:
    def test_fixture_components_match(self):
        assert set(_credentials_requests()) == {c.credentials_request for c in pol.COMPONENTS}

    @pytest.mark.parametrize("component", pol.COMPONENTS, ids=lambda c: c.key)
    def test_every_required_action_is_granted(self, component):
        required = set(_credentials_requests()[component.credentials_request])
        required -= INTENTIONALLY_DROPPED.get(component.credentials_request, set())
        granted = _allowed_actions(pol.component_policy(component.key, NAME, REGION, DOMAIN))
        missing = {a for a in required if not any(fnmatch.fnmatchcase(a, g) for g in granted)}
        assert not missing, f"{component.key} lacks {sorted(missing)}"


class TestSpokeInvariants:
    @pytest.mark.parametrize("label,doc", _spoke_policies().items())
    def test_no_wildcard_service_actions(self, label, doc):
        for a in _allowed_actions(doc):
            assert a != "*" and not a.endswith(":*"), f"{label}: {a}"
            assert not a.startswith("iam:") or a in {"iam:PassRole", "iam:CreateServiceLinkedRole", "iam:GetUser",
                                                     "iam:GetUserPolicy", "iam:ListAccessKeys"}, f"{label}: {a}"

    @pytest.mark.parametrize("label,doc", _spoke_policies().items())
    def test_mutating_actions_are_scoped(self, label, doc):
        """No mutating action on Resource '*' without a condition."""
        for st in _statements(doc):
            for a in _as_list(st["Action"]):
                verb = a.split(":")[1]
                if not verb.startswith(MUTATING):
                    continue
                assert st.get("Condition") or st["Resource"] != "*", f"{label}/{st['Sid']}: {a} is unscoped"

    def test_pass_role_only_own_node_roles(self):
        for label, doc in _spoke_policies().items():
            for st in _statements(doc):
                if "iam:PassRole" in _as_list(st["Action"]):
                    assert sorted(_as_list(st["Resource"])) == [
                        f"arn:aws:iam::*:role/{NAME}-master-role", f"arn:aws:iam::*:role/{NAME}-worker-role"], label
                    assert st["Condition"] == {"StringEquals": {"iam:PassedToService": "ec2.amazonaws.com"}}

    def test_instance_mutation_requires_cluster_profile(self):
        profile = {"ArnLike": {"ec2:InstanceProfile": f"arn:aws:iam::*:instance-profile/{PREFIX}-*"}}
        for label, doc in _spoke_policies().items():
            for st in _statements(doc):
                if st["Resource"] == pol._ec2("instance") and set(_as_list(st["Action"])) & {
                        "ec2:TerminateInstances", "ec2:ModifyInstanceAttribute", "ec2:AttachVolume", "ec2:RunInstances"}:
                    assert profile["ArnLike"].items() <= st["Condition"].get("ArnLike", {}).items(), f"{label}/{st['Sid']}"

    def test_ownership_tag_only_settable_at_create_or_on_owned(self):
        """CreateTags/AddTags never allowed on foreign resources (no claiming by tagging)."""
        for label, doc in _spoke_policies().items():
            for st in _statements(doc):
                if set(_as_list(st["Action"])) & {"ec2:CreateTags", "elasticloadbalancing:AddTags"}:
                    cond = json.dumps(st["Condition"])
                    assert any(k in cond for k in ("CreateAction", "ResourceTag", "InstanceProfile")), f"{label}/{st['Sid']}"

    def test_s3_limited_to_cluster_buckets(self):
        st = _statements(pol.component_policy("image-registry", NAME, REGION, DOMAIN))[0]
        assert st["Resource"] == [f"arn:aws:s3:::{PREFIX}-*", f"arn:aws:s3:::{PREFIX}-*/*"]

    def test_route53_limited_to_cluster_apps_records(self):
        doc = pol.component_policy("ingress", NAME, REGION, DOMAIN)
        st = next(s for s in _statements(doc) if "route53:ChangeResourceRecordSets" in s["Action"])
        names = st["Condition"]["ForAllValues:StringLike"]["route53:ChangeResourceRecordSetsNormalizedRecordNames"]
        assert names == [f"*.apps.{NAME}.{DOMAIN}", f"apps.{NAME}.{DOMAIN}"]

    @pytest.mark.parametrize("label,doc", _spoke_policies().items())
    def test_fits_policy_size_limit(self, label, doc):
        limit = pol.INLINE_ROLE_POLICY_MAX if label.endswith("-role") else pol.MANAGED_POLICY_MAX
        assert len(pol.render(doc)) <= limit, label

    @pytest.mark.parametrize("label,doc", _spoke_policies().items())
    def test_every_scaffold_tag_check_has_cluster_tag_twin(self, label, doc):
        """Post-install, resources tagged only kubernetes.io/cluster/<infraID> (CCM, CSI) stay manageable."""
        by_sid = {st["Sid"]: st for st in _statements(doc)}
        for sid, st in by_sid.items():
            if pol.TAG_KEY not in json.dumps(st.get("Condition", {})):
                continue
            twin = by_sid.get(f"{sid}ByClusterTag")
            assert twin, f"{label}/{sid} has no ByClusterTag twin"
            assert (twin["Action"], twin["Resource"]) == (st["Action"], st["Resource"])
            cond = json.dumps(twin["Condition"])
            assert pol.CLUSTER_TAG in cond and pol.TAG_KEY not in cond
            # Non-tag conditions (e.g. instance profile) are kept on both
            assert {k for k in st["Condition"] if k != "StringEquals"} == {k for k in twin["Condition"] if k != "StringEquals"}

    def test_egress_ip_changes_limited_to_cluster_vpc(self):
        doc = pol.component_policy("cncc", NAME, REGION, DOMAIN)
        st = next(s for s in _statements(doc) if s["Sid"] == "EgressIPs")
        assert st["Condition"] == {"ArnLike": {"ec2:Vpc": f"arn:aws:ec2:*:*:vpc/{pol.VPC_ID_PLACEHOLDER}"}}

    def test_placeholders_fail_closed_until_substituted(self):
        """Placeholders are literal values that cannot match a real infra ID or VPC ID."""
        assert pol.INFRA_ID_PLACEHOLDER == "INFRA_ID_PLACEHOLDER"
        assert pol.VPC_ID_PLACEHOLDER == "VPC_ID_PLACEHOLDER"
        rendered = " ".join(pol.render(d) for d in _spoke_policies().values())
        assert pol.CLUSTER_TAG in rendered and pol.VPC_ID_PLACEHOLDER in rendered


class TestInstallerPolicy:
    def test_no_iam_escalation_actions(self):
        doc = pol.installer_policy(NAME)
        granted = _allowed_actions(doc)
        forbidden = {"iam:*", "iam:CreateUser", "iam:CreateAccessKey", "iam:PutUserPolicy", "iam:AttachUserPolicy",
                     "iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy", "iam:CreatePolicy",
                     "iam:CreatePolicyVersion", "iam:UpdateAssumeRolePolicy", "sts:*", "*"}
        assert not granted & forbidden

    def test_iam_writes_limited_to_cluster(self):
        for st in _statements(pol.installer_policy(NAME)):
            writes = [a for a in _as_list(st["Action"])
                      if a.startswith("iam:") and not a.split(":")[1].startswith(("Get", "List", "Simulate"))]
            if writes:
                assert st["Resource"] in (f"arn:aws:iam::*:role/{NAME}-*", f"arn:aws:iam::*:instance-profile/{PREFIX}-*"), st["Sid"]


class TestComponents:
    def test_iam_name_budget(self):
        assert pol.MAX_NAME_SUFFIX == len("-image-registry")

    def test_secret_targets_match_credentials_requests(self):
        targets = {}
        for f in sorted(FIXTURES.glob("*.yaml")):
            for d in yaml.safe_load_all(f.read_text()):
                if d:
                    targets[d["metadata"]["name"]] = (d["spec"]["secretRef"]["namespace"], d["spec"]["secretRef"]["name"])
        for c in pol.COMPONENTS:
            assert targets[c.credentials_request] == (c.namespace, c.secret), c.key
