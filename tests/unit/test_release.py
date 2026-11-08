"""Loader tests for scaffold.release (CredentialsRequest manifests)."""

import pathlib

import pytest
import yaml

from scaffold.providers.aws_policies import COMPONENTS
from scaffold.release import ReleaseError, load_credentials_requests

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "credentialsrequests" / "aws-4.21"


def _cr(name, *statements, kind="CredentialsRequest", namespace="ns", secret="creds", provider="AWSProviderSpec"):
    """A CredentialsRequest document; each statement is (effect, actions), effect None omits the key."""
    entries = []
    for effect, actions in statements:
        st = {"action": list(actions), "resource": "*"}
        if effect is not None:
            st["effect"] = effect
        entries.append(st)
    return {
        "apiVersion": "cloudcredential.openshift.io/v1",
        "kind": kind,
        "metadata": {"name": name, "namespace": "openshift-cloud-credential-operator"},
        "spec": {
            "providerSpec": {"kind": provider, "statementEntries": entries},
            "secretRef": {"name": secret, "namespace": namespace},
        },
    }


def _write(path, *docs):
    path.write_text(yaml.safe_dump_all(docs, sort_keys=False))


class TestLoadCredentialsRequests:
    def test_fixtures_parse_to_the_scoped_components(self):
        requests = load_credentials_requests(FIXTURES)
        assert len(requests) == 6
        assert {r.name for r in requests} == {c.credentials_request for c in COMPONENTS}
        assert all(r.provider_kind == "AWSProviderSpec" for r in requests)
        ingress = next(r for r in requests if r.name == "openshift-ingress")
        assert {"route53:ChangeResourceRecordSets", "sts:AssumeRole"} <= set(ingress.actions)
        assert (ingress.namespace, ingress.secret) == ("openshift-ingress-operator", "cloud-credentials")

    def test_multi_document_files_in_sorted_order(self, tmp_path):
        # a.yaml sorts before b.yml; the empty document between the two in a.yaml is skipped
        first = yaml.safe_dump(_cr("first", ("Allow", ["ec2:DescribeInstances"])), sort_keys=False)
        second = yaml.safe_dump(_cr("second", ("Allow", ["ec2:DescribeVolumes"])), sort_keys=False)
        (tmp_path / "a.yaml").write_text(f"---\n{first}---\n---\n{second}")
        _write(tmp_path / "b.yml", _cr("third", ("Allow", ["s3:GetObject"])))
        (tmp_path / "notes.txt").write_text("kind: CredentialsRequest\n")  # not a manifest extension
        assert [r.name for r in load_credentials_requests(tmp_path)] == ["first", "second", "third"]

    def test_other_kinds_are_skipped(self, tmp_path):
        _write(tmp_path / "x.yaml", _cr("secret", ("Allow", ["ec2:A"]), kind="Secret"), _cr("real", ("Allow", ["ec2:A"])))
        assert [r.name for r in load_credentials_requests(tmp_path)] == ["real"]

    def test_actions_are_deduplicated_in_file_order(self, tmp_path):
        _write(tmp_path / "x.yaml", _cr("dup", ("Allow", ["ec2:B", "ec2:A"]), ("Allow", ["ec2:A", "ec2:C"])))
        (r,) = load_credentials_requests(tmp_path)
        assert r.actions == ("ec2:B", "ec2:A", "ec2:C")

    def test_deny_statements_are_ignored_and_effect_defaults_to_allow(self, tmp_path):
        _write(tmp_path / "x.yaml", _cr("mixed", ("Allow", ["ec2:A"]), ("Deny", ["ec2:Z"]), (None, ["ec2:B"])))
        (r,) = load_credentials_requests(tmp_path)
        assert r.actions == ("ec2:A", "ec2:B")

    def test_fields_come_from_the_manifest(self, tmp_path):
        _write(tmp_path / "x.yaml", _cr("az", ("Allow", ["Microsoft.Network/read"]),
                                        namespace="openshift-ingress-operator", secret="cloud-credentials",
                                        provider="AzureProviderSpec"))
        (r,) = load_credentials_requests(tmp_path)
        assert (r.name, r.provider_kind, r.namespace, r.secret) == (
            "az", "AzureProviderSpec", "openshift-ingress-operator", "cloud-credentials")

    def test_non_directory_raises(self, tmp_path):
        with pytest.raises(ReleaseError, match="not a directory"):
            load_credentials_requests(tmp_path / "missing")
        (tmp_path / "file.yaml").write_text("")
        with pytest.raises(ReleaseError, match="not a directory"):
            load_credentials_requests(tmp_path / "file.yaml")

    def test_no_credentials_requests_raises(self, tmp_path):
        _write(tmp_path / "x.yaml", _cr("secret", ("Allow", ["ec2:A"]), kind="Secret"))
        with pytest.raises(ReleaseError, match="no CredentialsRequests"):
            load_credentials_requests(tmp_path)

    def test_malformed_manifest_raises_naming_the_file(self, tmp_path):
        (tmp_path / "broken.yaml").write_text("kind: CredentialsRequest\nmetadata: {name: broken}\nspec: {}\n")
        with pytest.raises(ReleaseError, match="broken.yaml"):
            load_credentials_requests(tmp_path)
