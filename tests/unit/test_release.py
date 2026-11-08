"""Tests for scaffold.release: manifest loader, image-set mapping, oc extraction (mocked)."""

import os
import pathlib
import shutil
import subprocess
from unittest import mock

import pytest
import yaml

from scaffold.providers.aws_policies import COMPONENTS
from scaffold.release import (
    RELEASE_REPOSITORY,
    ReleaseError,
    extract_credentials_requests,
    load_credentials_requests,
    release_image_for,
)

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "credentialsrequests" / "aws-4.21"
INSTALL_CONFIG = "apiVersion: v1\nbaseDomain: example.com\nmetadata:\n  name: demo\n"
IMAGE = f"{RELEASE_REPOSITORY}:4.21.13-x86_64"


def _copy_fixtures(argv, **_kwargs):
    """Stand-in for oc: write the vendored 4.21 manifests where --to points."""
    to = next(a for a in argv if a.startswith("--to=")).removeprefix("--to=")
    os.makedirs(to)
    for f in FIXTURES.glob("*.yaml"):
        shutil.copy(f, to)
    return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


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


class TestReleaseImageFor:
    def test_maps_the_hub_image_set_convention(self):
        assert release_image_for("img4.21.13-x86-64-appsub") == "quay.io/openshift-release-dev/ocp-release:4.21.13-x86_64"
        assert release_image_for("img4.22.9-x86-64-appsub") == "quay.io/openshift-release-dev/ocp-release:4.22.9-x86_64"

    @pytest.mark.parametrize("image_set", ["custom-name", "img4.21-x86-64-appsub", "img4.21.13-arm64-appsub"])
    def test_other_names_point_at_the_overrides(self, image_set):
        with pytest.raises(ReleaseError) as exc:
            release_image_for(image_set)
        message = str(exc.value)
        assert image_set in message
        assert "--release-image" in message and "--skip-release-check" in message


class TestExtractCredentialsRequests:
    @mock.patch("scaffold.release.subprocess.run", side_effect=_copy_fixtures)
    @mock.patch("scaffold.release.shutil.which", return_value="/usr/bin/oc")
    def test_runs_oc_with_the_install_config_and_parses_the_output(self, which, run, tmp_path):
        requests = extract_credentials_requests(IMAGE, INSTALL_CONFIG, "aws", str(tmp_path))
        assert {r.name for r in requests} == {c.credentials_request for c in COMPONENTS}
        which.assert_called_once_with("oc")
        (call,) = run.call_args_list
        assert call.args == ([
            "oc", "adm", "release", "extract", "--credentials-requests", "--cloud=aws", "--included",
            f"--install-config={os.path.join(tmp_path, 'install-config.yaml')}",
            f"--to={os.path.join(tmp_path, 'credentials-requests')}", IMAGE],)
        assert call.kwargs == {"capture_output": True, "text": True, "timeout": 300}
        assert (tmp_path / "install-config.yaml").read_text() == INSTALL_CONFIG

    @mock.patch("scaffold.release.subprocess.run")
    @mock.patch("scaffold.release.shutil.which", return_value=None)
    def test_missing_oc_fails_before_running_anything(self, which, run, tmp_path):
        with pytest.raises(ReleaseError, match="oc not found on PATH"):
            extract_credentials_requests(IMAGE, INSTALL_CONFIG, "aws", str(tmp_path))
        run.assert_not_called()

    @mock.patch("scaffold.release.shutil.which", return_value="/usr/bin/oc")
    def test_non_zero_exit_reports_image_and_stderr(self, which, tmp_path):
        proc = subprocess.CompletedProcess([], 1, stdout="", stderr="error: unauthorized: access denied\n")
        with mock.patch("scaffold.release.subprocess.run", return_value=proc):
            with pytest.raises(ReleaseError) as exc:
                extract_credentials_requests(IMAGE, INSTALL_CONFIG, "aws", str(tmp_path))
        assert IMAGE in str(exc.value) and "unauthorized: access denied" in str(exc.value)

    @mock.patch("scaffold.release.shutil.which", return_value="/usr/bin/oc")
    def test_timeout_is_a_release_error(self, which, tmp_path):
        with mock.patch("scaffold.release.subprocess.run", side_effect=subprocess.TimeoutExpired(["oc"], 300)):
            with pytest.raises(ReleaseError, match="timed out after 300s"):
                extract_credentials_requests(IMAGE, INSTALL_CONFIG, "aws", str(tmp_path))
