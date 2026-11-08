import logging
import os
import shutil
from pathlib import Path
import subprocess
from unittest import mock

import pytest
import yaml

from scaffold.cli import main
from scaffold.providers import aws_policies as pol
from scaffold.providers.base import (
    ANNOTATION_CREDENTIALS_REQUEST,
    ANNOTATION_TARGET_NAMESPACE,
    ANNOTATION_TARGET_SECRET,
)
from scaffold.release import ReleaseError, load_credentials_requests

FIXTURES = Path(__file__).parent.parent / "fixtures" / "credentialsrequests" / "aws-4.21"
RELEASE_IMAGE = "quay.io/openshift-release-dev/ocp-release:4.21.13-x86_64"


@pytest.fixture(autouse=True)
def release_from_fixtures():
    """Every CLI run compares the scoped policies against the vendored 4.21 CredentialsRequests; no oc, no network."""
    with mock.patch("scaffold.release.extract_credentials_requests",
                    return_value=load_credentials_requests(FIXTURES)) as extract:
        yield extract


@pytest.fixture()
def default_args(tmp_path):
    """Return a list of CLI arguments for the standard scaffold command."""
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    return [
        "aws",
        "--name",
        "my-cluster",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--topology",
        "standard",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]


# ======== Original integration tests (adapted) ========

@mock.patch("scaffold.cli.shutil.which")
@mock.patch("scaffold.cli.subprocess.run")
def test_scaffold_writes_and_validates(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        [], returncode=0, stdout="", stderr=""
    )
    mock_which.return_value = "/usr/bin/kustomize"
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    args = [
        "aws",
        "--name",
        "test-01",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--topology",
        "standard",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    main(args)
    assert (tmp_path / "test-01" / "kustomization.yaml").exists()
    assert (tmp_path / "test-01" / "hive" / "kustomization.yaml").exists()
    assert (tmp_path / "test-01" / "crossplane" / "kustomization.yaml").exists()
    assert mock_run.call_count == 2


@mock.patch("scaffold.cli.shutil.which")
@mock.patch("scaffold.cli.subprocess.run")
def test_scaffold_fails_on_invalid_kustomize(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        [], returncode=1, stdout="", stderr="error"
    )
    mock_which.return_value = "/usr/bin/kustomize"
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    args = [
        "aws",
        "--name",
        "bad-cluster",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--topology",
        "standard",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    assert main(args) == 1


@mock.patch("scaffold.cli.shutil.which")
@mock.patch("scaffold.cli.subprocess.run")
def test_scaffold_with_custom_zones(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        [], returncode=0, stdout="", stderr=""
    )
    mock_which.return_value = "/usr/bin/kustomize"
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    args = [
        "aws",
        "--name",
        "zoned",
        "--region",
        "eu-west-1",
        "--tier",
        "ai",
        "--zones",
        "eu-west-1a,eu-west-1c",
        "--environment",
        "production",
        "--topology",
        "standard",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    main(args)
    assert (tmp_path / "zoned" / "kustomization.yaml").exists()


@pytest.mark.parametrize("accelerator", ["none", "nvidia-gpu"])
def test_scaffold_writes_ai_accelerator(default_args, accelerator):
    args = default_args.copy()
    args[args.index("--tier") + 1] = "ai"
    args += ["--ai-accelerator", accelerator, "--skip-validation"]
    assert main(args) == 0
    base_path = Path(args[args.index("--base-path") + 1])
    metadata = yaml.safe_load((base_path / "my-cluster" / "metadata.yaml").read_text())
    assert metadata["ai-accelerator"] == accelerator


@pytest.mark.parametrize("accelerator", ["none", "nvidia-gpu"])
def test_rejects_ai_accelerator_without_ai_tier(default_args, accelerator):
    args = [*default_args, "--ai-accelerator", accelerator]
    assert main(args) == 1
    base_path = Path(args[args.index("--base-path") + 1])
    assert not (base_path / "my-cluster").exists()


# ======== NEW tests for new features ========

@mock.patch("scaffold.cli.shutil.which")
def test_shows_kustomize_missing_error(mock_which, tmp_path):
    mock_which.return_value = None
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    args = [
        "aws",
        "--name",
        "no-kust",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--topology",
        "standard",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    assert main(args) == 1


@mock.patch("scaffold.cli.subprocess.run")
def test_skip_validation_suppresses_kustomize_run(mock_run, default_args):
    main(default_args + ["--skip-validation"])
    mock_run.assert_not_called()


@mock.patch("scaffold.cli.subprocess.run")
def test_no_skip_validates_kustomize_run(mock_run, default_args):
    with mock.patch(
        "scaffold.cli.shutil.which", return_value="kustomize"
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            [], returncode=0, stdout="", stderr=""
        )
        main(default_args)
    assert mock_run.call_count == 2


@mock.patch("scaffold.cli.shutil.which")
def test_skip_validation_skips_kustomize_check(mock_which, tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    main([
        "aws",
        "--name", "x",
        "--region", "r",
        "--tier", "base",
        "--environment", "dev",
        "--topology", "standard",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    mock_which.assert_not_called()



@mock.patch("scaffold.cli.subprocess.run")
def test_worker_type_used_verbatim_without_profile(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    with mock.patch("scaffold.cli.shutil.which", return_value="kustomize"):
        main([
            "aws",
            "--name", "wt",
            "--region", "us-east-1",
            "--tier", "base",
            "--worker-type", "c5.4xlarge",
            "--base-path", str(tmp_path),
            "--cluster-templates-dir", str(tpl_dir),
        ])
    mp = yaml.safe_load((tmp_path / "wt" / "hive" / "patches" / "machinepool-worker.yaml").read_text())
    type_ops = [op for op in mp if op["path"] == "/spec/platform/aws/type"]
    assert type_ops[0]["value"] == "c5.4xlarge"


@mock.patch("scaffold.cli.subprocess.run")
def test_worker_type_used_even_with_profile(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    with mock.patch("scaffold.cli.shutil.which", return_value="kustomize"):
        main([
            "aws",
            "--name", "wt2",
            "--region", "us-east-1",
            "--tier", "base",
            "--worker-type", "r6i.xlarge",
            "--topology", "standard",
            "--base-path", str(tmp_path),
            "--cluster-templates-dir", str(tpl_dir),
        ])
    mp = yaml.safe_load((tmp_path / "wt2" / "hive" / "patches" / "machinepool-worker.yaml").read_text())
    type_ops = [op for op in mp if op["path"] == "/spec/platform/aws/type"]
    assert type_ops[0]["value"] == "r6i.xlarge"


def test_base_domain_forwarded_to_output(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    main([
        "aws",
        "--name", "bd",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-domain", "custom.example.com",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    ic = yaml.safe_load((tmp_path / "bd" / "hive" / "patches" / "install-config.yaml").read_text())
    embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
    assert embedded["baseDomain"] == "custom.example.com"


def test_base_domain_default_when_omitted(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    main([
        "aws",
        "--name", "bd2",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    ic = yaml.safe_load((tmp_path / "bd2" / "hive" / "patches" / "install-config.yaml").read_text())
    embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
    assert embedded["baseDomain"] == "openshiftpartnerlabs.com"


def test_profile_forwarded_to_kustomization_resource(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    main([
        "aws",
        "--name", "pf",
        "--region", "us-east-1",
        "--tier", "base",
        "--topology", "standard",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    kust = yaml.safe_load((tmp_path / "pf" / "hive" / "kustomization.yaml").read_text())
    assert "aws/standard/hive" in kust["resources"][0]


def test_rejects_invalid_cluster_name(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    tpl_dir.mkdir()
    result = main([
        "aws",
        "--name", "INVALID_NAME!",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    assert result == 1


# ======== Overwrite protection tests ========


def test_refuses_overwrite_when_dir_exists(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    (tmp_path / "existing").mkdir()
    result = main([
        "aws",
        "--name", "existing",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    assert result == 1


def test_force_allows_overwrite(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    (tmp_path / "existing").mkdir()
    result = main([
        "aws",
        "--name", "existing",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
        "--force",
    ])
    assert result == 0
    assert (tmp_path / "existing" / "kustomization.yaml").exists()


def test_fresh_directory_without_force(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    (tpl_dir / "aws" / "standard").mkdir(parents=True)
    result = main([
        "aws",
        "--name", "fresh",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    assert result == 0
    assert (tmp_path / "fresh" / "kustomization.yaml").exists()


# ======== Cloud subcommand tests ========


def test_cloud_subcommand_required(tmp_path):
    with pytest.raises(SystemExit):
        main(["--name", "x", "--region", "r", "--tier", "base"])


@pytest.mark.parametrize("cloud", ["gcp", "ibmcloud"])
def test_planned_provider_not_supported(cloud, tmp_path):
    assert main([cloud, "--name", "x", "--base-path", str(tmp_path)]) == 1
    assert not (tmp_path / "x").exists()


def test_unknown_flag_rejected_for_implemented_provider(default_args):
    with pytest.raises(SystemExit):
        main(default_args + ["--skip-validation", "--bogus"])


# ======== Topology tests ========


def test_topology_selects_template_and_replicas(tmp_path):
    (tmp_path / "cluster-templates" / "aws" / "sno").mkdir(parents=True)
    assert main([
        "aws", "--name", "sno1", "--region", "us-east-1", "--tier", "base",
        "--topology", "sno",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tmp_path / "cluster-templates"),
        "--skip-validation",
    ]) == 0
    hive = tmp_path / "sno1" / "hive"
    assert "aws/sno/hive" in yaml.safe_load((hive / "kustomization.yaml").read_text())["resources"][0]
    assert not (hive / "patches" / "machinepool-worker.yaml").exists()
    ic = yaml.safe_load((hive / "patches" / "install-config.yaml").read_text())
    embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
    assert embedded["controlPlane"]["replicas"] == 1
    assert embedded["compute"][0] == {
        "name": "worker",
        "replicas": 0,
        "platform": {
            "aws": {
                "iamRole": "sno1-worker-role",
                "rootVolume": {"iops": 4000, "size": 100, "type": "gp3"},
                "type": "m7i.2xlarge",
                "zones": ["us-east-1a", "us-east-1b", "us-east-1c"],
            }
        },
    }


# ======== AWS credential mode tests ========


def _aws_args(tmp_path, name, *extra):
    (tmp_path / "cluster-templates" / "aws" / "standard").mkdir(parents=True, exist_ok=True)
    return [
        "aws", "--name", name, "--region", "us-east-2", "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tmp_path / "cluster-templates"),
        "--skip-validation", *extra,
    ]


def _embedded_install_config(cluster_dir):
    ic = yaml.safe_load((cluster_dir / "hive" / "patches" / "install-config.yaml").read_text())
    return yaml.safe_load(ic["stringData"]["install-config.yaml"])


def test_aws_defaults_to_scoped_credentials(tmp_path):
    assert main(_aws_args(tmp_path, "sc1")) == 0
    cluster = tmp_path / "sc1"
    ic = _embedded_install_config(cluster)
    assert ic["credentialsMode"] == "Manual"
    assert ic["platform"]["aws"]["userTags"] == {"openshiftpartnerlabs.com/cluster": "sc1"}
    assert ic["platform"]["aws"]["propagateUserTags"] is True
    assert ic["controlPlane"]["platform"]["aws"]["iamRole"] == "sc1-master-role"
    assert ic["compute"][0]["platform"]["aws"]["iamRole"] == "sc1-worker-role"
    cd = yaml.safe_load((cluster / "hive" / "patches" / "clusterdeployment.yaml").read_text())
    assert {"op": "add", "path": "/spec/provisioning/manifestsSecretRef",
            "value": {"name": "sc1-cloud-credentials-manifests"}} in cd
    mp = yaml.safe_load((cluster / "hive" / "patches" / "machinepool-worker.yaml").read_text())
    assert {"op": "add", "path": "/spec/platform/aws/userTags",
            "value": {"openshiftpartnerlabs.com/cluster": "sc1"}} in mp
    kust = yaml.safe_load((cluster / "crossplane" / "kustomization.yaml").read_text())
    assert kust["resources"][0].endswith("aws/standard/crossplane-scoped")
    assert yaml.safe_load((cluster / "metadata.yaml").read_text()) == {"platform": "aws", "aws-credentials-mode": "scoped"}


def test_aws_legacy_flag_keeps_mint_mode(tmp_path, caplog):
    assert main(_aws_args(tmp_path, "lg1", "--legacy-mint-credentials")) == 0
    cluster = tmp_path / "lg1"
    ic = _embedded_install_config(cluster)
    assert "credentialsMode" not in ic
    assert "iamRole" not in ic["controlPlane"]["platform"]["aws"]
    kust = yaml.safe_load((cluster / "crossplane" / "kustomization.yaml").read_text())
    assert kust["resources"][0].endswith("aws/standard/crossplane")
    assert yaml.safe_load((cluster / "metadata.yaml").read_text())["aws-credentials-mode"] == "legacy"
    assert "account-admin" in caplog.text


def test_aws_scoped_rejects_names_too_long_for_iam(tmp_path):
    assert main(_aws_args(tmp_path, "a" * 50)) == 1
    assert main(_aws_args(tmp_path, "a" * 49)) == 0


# ======== Azure tests ========

SUB_ID = "11111111-2222-3333-4444-555555555555"


def _azure_args(tmp_path, name="az-cluster", *extra):
    (tmp_path / "cluster-templates" / "azure" / "standard").mkdir(parents=True, exist_ok=True)
    return [
        "azure",
        "--name", name,
        "--region", "eastus2",
        "--tier", "base",
        "--subscription-id", SUB_ID,
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tmp_path / "cluster-templates"),
        "--skip-validation",
        *extra,
    ]


def test_azure_requires_subscription_id(tmp_path):
    args = _azure_args(tmp_path)
    i = args.index("--subscription-id")
    with pytest.raises(SystemExit):
        main(args[:i] + args[i + 2:])


def test_azure_rejects_invalid_subscription_id(tmp_path):
    args = _azure_args(tmp_path)
    args[args.index(SUB_ID)] = "not-a-uuid"
    assert main(args) == 1


def test_azure_scaffold_uses_azure_defaults(tmp_path):
    assert main(_azure_args(tmp_path)) == 0
    hive = tmp_path / "az-cluster" / "hive"
    kust = yaml.safe_load((hive / "kustomization.yaml").read_text())
    assert "azure/standard/hive" in kust["resources"][0]
    ic = yaml.safe_load((hive / "patches" / "install-config.yaml").read_text())
    embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
    assert embedded["controlPlane"]["platform"]["azure"]["type"] == "Standard_D8s_v5"
    assert embedded["controlPlane"]["platform"]["azure"]["zones"] == ["1", "2", "3"]
    assert embedded["platform"]["azure"]["resourceGroupName"] == "az-cluster-rg"
    assert (tmp_path / "az-cluster" / "crossplane" / "patches" / "role-assignment-contributor.yaml").exists()


def test_azure_metadata_for_pipeline(tmp_path):
    main(_azure_args(tmp_path, "az3", "--base-domain-resource-group", "dns-rg"))
    assert yaml.safe_load((tmp_path / "az3" / "metadata.yaml").read_text()) == {
        "platform": "azure",
        "azure-subscription-id": SUB_ID,
        "azure-dns-resource-group": "dns-rg",
    }


def test_azure_flags_forwarded(tmp_path):
    main(_azure_args(
        tmp_path, "az2",
        "--base-domain-resource-group", "dns-rg",
        "--cloud-name", "AzureUSGovernmentCloud",
        "--worker-type", "Standard_D16s_v5",
    ))
    cd = yaml.safe_load((tmp_path / "az2" / "hive" / "patches" / "clusterdeployment.yaml").read_text())
    ops = {op["path"]: op["value"] for op in cd}
    assert ops["/spec/platform/azure/baseDomainResourceGroupName"] == "dns-rg"
    assert ops["/spec/platform/azure/cloudName"] == "AzureUSGovernmentCloud"
    mp = yaml.safe_load((tmp_path / "az2" / "hive" / "patches" / "machinepool-worker.yaml").read_text())
    assert {op["path"]: op["value"] for op in mp}["/spec/platform/azure/type"] == "Standard_D16s_v5"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ======== Install attempts tests ========


def _cd_ops(cluster_dir):
    cd = yaml.safe_load((cluster_dir / "hive" / "patches" / "clusterdeployment.yaml").read_text())
    return {op["path"]: op["value"] for op in cd}


def test_install_attempts_limit_defaults_to_one(tmp_path):
    assert main(_aws_args(tmp_path, "ia1")) == 0
    assert _cd_ops(tmp_path / "ia1")["/spec/installAttemptsLimit"] == 1


def test_install_attempts_limit_override(tmp_path):
    assert main(_aws_args(tmp_path, "ia3", "--install-attempts-limit", "3")) == 0
    assert _cd_ops(tmp_path / "ia3")["/spec/installAttemptsLimit"] == 3


def test_install_attempts_limit_rejects_zero(tmp_path):
    assert main(_aws_args(tmp_path, "ia0", "--install-attempts-limit", "0")) == 1
    assert not (tmp_path / "ia0").exists()


# ======== Worker replicas vs topology ========


@pytest.mark.parametrize("topology", ["compact", "sno"])
def test_worker_replicas_rejected_without_worker_pool(tmp_path, topology):
    assert main(_aws_args(tmp_path, "wr1", "--topology", topology, "--worker-replicas", "2")) == 1
    assert not (tmp_path / "wr1").exists()


@pytest.mark.parametrize("topology,extra", [("compact", []), ("sno", ["--worker-replicas", "0"]),
                                            ("standard", ["--worker-replicas", "2"])])
def test_worker_replicas_accepted(tmp_path, topology, extra):
    (tmp_path / "cluster-templates" / "aws" / topology).mkdir(parents=True, exist_ok=True)
    assert main(_aws_args(tmp_path, "wr2", "--topology", topology, *extra)) == 0


# ======== Unpatched base-template detection ========

REPO_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "..", "cluster-templates")
_AZURE_SUB = "00000000-0000-0000-0000-000000000000"
needs_kustomize = pytest.mark.skipif(shutil.which("kustomize") is None, reason="kustomize not installed")


def _validate_args(tmp_path, cloud, topology, templates):
    extra = ["--subscription-id", _AZURE_SUB] if cloud == "azure" else []
    region = "eastus2" if cloud == "azure" else "us-east-2"
    return [
        cloud, "--name", f"v-{topology}", "--region", region, "--tier", "base", "--topology", topology,
        "--base-path", str(tmp_path / "out"), "--cluster-templates-dir", str(templates), *extra,
    ]


@mock.patch("scaffold.cli.shutil.which", return_value="/usr/bin/kustomize")
@mock.patch("scaffold.cli.subprocess.run")
def test_validation_fails_when_base_names_survive(mock_run, _which, default_args):
    mock_run.return_value = subprocess.CompletedProcess(
        [], returncode=0, stdout="metadata:\n  name: cluster-placeholder-federated-cred\n", stderr=""
    )
    assert main(default_args) == 1


@needs_kustomize
@pytest.mark.parametrize("cloud", ["aws", "azure"])
@pytest.mark.parametrize("topology", ["standard", "compact", "sno"])
def test_repo_templates_render_without_base_names(cloud, topology, tmp_path):
    assert main(_validate_args(tmp_path, cloud, topology, REPO_TEMPLATES)) == 0


@needs_kustomize
def test_stale_base_is_rejected(tmp_path):
    """A base whose resource names differ from the patch targets renders fine but must fail validation."""
    templates = tmp_path / "cluster-templates"
    shutil.copytree(os.path.join(REPO_TEMPLATES, "azure"), templates / "azure")
    rg = templates / "azure" / "standard" / "crossplane" / "resource-group.yaml"
    rg.write_text(rg.read_text().replace("name: cluster-placeholder-rg", "name: cluster-placeholder-old-rg"))
    assert main(_validate_args(tmp_path, "azure", "standard", templates)) == 1


@needs_kustomize
def test_scoped_access_keys_carry_target_annotations(tmp_path):
    """The rendered overlay, not only the patch files: kustomize applies the add op onto the base AccessKeys."""
    assert main(_validate_args(tmp_path, "aws", "standard", REPO_TEMPLATES)) == 0
    built = subprocess.run(["kustomize", "build", str(tmp_path / "out" / "v-standard" / "crossplane")],
                           capture_output=True, text=True, check=True)
    access_keys = {d["metadata"]["name"]: d["metadata"].get("annotations", {})
                   for d in yaml.safe_load_all(built.stdout) if d and d["kind"] == "AccessKey"}
    for c in pol.COMPONENTS:
        assert access_keys[f"v-standard-{c.key}-access-key"] == {
            ANNOTATION_CREDENTIALS_REQUEST: c.credentials_request,
            ANNOTATION_TARGET_NAMESPACE: c.namespace,
            ANNOTATION_TARGET_SECRET: c.secret,
        }
    assert ANNOTATION_TARGET_SECRET not in access_keys["v-standard-access-key"]


# ======== Release check (scoped AWS policies vs the release's CredentialsRequests) ========

MACHINE_API_FIXTURE = "0000_30_machine-api-operator_00_credentials-request.yaml"
INGRESS_FIXTURE = "0000_50_cluster-ingress-operator_00-ingress-credentials-request.yaml"


def _fixtures_copy(tmp_path):
    return Path(shutil.copytree(FIXTURES, tmp_path / "credentials-requests"))


def _load_one(path):
    return next(d for d in yaml.safe_load_all(path.read_text()) if d)


def test_release_check_runs_against_the_image_set_release(tmp_path, caplog, release_from_fixtures):
    caplog.set_level(logging.INFO, logger="scaffold")
    assert main(_aws_args(tmp_path, "rc1")) == 0
    # Announced before the extraction: oc prints nothing while it pulls
    assert (f"  -> release check: extracting CredentialsRequests from {RELEASE_IMAGE} "
            "(oc adm release extract, up to 300s)") in caplog.text
    assert f"Release check: 6 CredentialsRequests from {RELEASE_IMAGE} covered by the scoped policies." in caplog.text
    (call,) = release_from_fixtures.call_args_list
    image, install_config, cloud, _workdir = call.args
    assert (image, cloud) == (RELEASE_IMAGE, "aws")
    # The extraction sees the same install-config the overlay embeds (capabilities and feature set drive --included)
    ic = yaml.safe_load((tmp_path / "rc1" / "hive" / "patches" / "install-config.yaml").read_text())
    assert install_config == ic["stringData"]["install-config.yaml"]
    assert yaml.safe_load(install_config)["credentialsMode"] == "Manual"


def test_release_image_override_is_forwarded(tmp_path, release_from_fixtures):
    assert main(_aws_args(tmp_path, "rc2", "--release-image", "quay.io/example/release:1")) == 0
    assert release_from_fixtures.call_args.args[0] == "quay.io/example/release:1"


def test_unknown_image_set_fails_closed(tmp_path, caplog, release_from_fixtures):
    assert main(_aws_args(tmp_path, "rc3", "--image-set", "custom-name")) == 1
    assert "Release check failed:" in caplog.text
    assert "--release-image" in caplog.text and "--skip-release-check" in caplog.text
    release_from_fixtures.assert_not_called()


def test_skip_release_check(tmp_path, caplog, release_from_fixtures):
    caplog.set_level(logging.INFO, logger="scaffold")
    assert main(_aws_args(tmp_path, "rc4", "--skip-release-check")) == 0
    assert ("Skipping release check (--skip-release-check): the scoped policies were not verified against "
            "img4.21.13-x86-64-appsub.") in caplog.text
    release_from_fixtures.assert_not_called()


def test_credentials_requests_dir_replaces_extraction(tmp_path, caplog, release_from_fixtures):
    caplog.set_level(logging.INFO, logger="scaffold")
    assert main(_aws_args(tmp_path, "rc5", "--credentials-requests-dir", str(FIXTURES))) == 0
    assert f"Release check: 6 CredentialsRequests from {FIXTURES} covered by the scoped policies." in caplog.text
    release_from_fixtures.assert_not_called()


def test_operator_without_scoped_policy_fails(tmp_path, caplog):
    crs = _fixtures_copy(tmp_path)
    extra = _load_one(crs / MACHINE_API_FIXTURE)
    extra["metadata"]["name"] = "openshift-cluster-api-aws"
    (crs / "zz_cluster-api.yaml").write_text(yaml.safe_dump(extra))
    assert main(_aws_args(tmp_path, "rc6", "--credentials-requests-dir", str(crs))) == 1
    assert f"Release check failed against {crs}:" in caplog.text
    assert "no scoped policy for CredentialsRequest 'openshift-cluster-api-aws'" in caplog.text
    assert "Update aws_policies.py" in caplog.text


def test_action_missing_from_scoped_policy_fails(tmp_path, caplog):
    crs = _fixtures_copy(tmp_path)
    doc = _load_one(crs / MACHINE_API_FIXTURE)
    doc["spec"]["providerSpec"]["statementEntries"][0]["action"].append("ec2:AllocateHosts")
    (crs / MACHINE_API_FIXTURE).write_text(yaml.safe_dump(doc))
    assert main(_aws_args(tmp_path, "rc7", "--credentials-requests-dir", str(crs))) == 1
    assert "machine-api lacks ec2:AllocateHosts" in caplog.text


def test_operator_absent_from_release_fails(tmp_path, caplog):
    crs = _fixtures_copy(tmp_path)
    (crs / INGRESS_FIXTURE).unlink()
    assert main(_aws_args(tmp_path, "rc8", "--credentials-requests-dir", str(crs))) == 1
    assert "ingress: CredentialsRequest 'openshift-ingress' is not in this release" in caplog.text


def test_extraction_error_fails(tmp_path, caplog, release_from_fixtures):
    release_from_fixtures.side_effect = ReleaseError("boom")
    assert main(_aws_args(tmp_path, "rc9")) == 1
    assert "Release check failed: boom" in caplog.text


def test_release_check_not_applicable_without_scoped_policies(tmp_path, caplog, release_from_fixtures):
    caplog.set_level(logging.INFO, logger="scaffold")
    assert main(_aws_args(tmp_path, "rc10", "--legacy-mint-credentials")) == 0
    assert main(_azure_args(tmp_path, "rc11")) == 0
    assert caplog.text.count("Release check not applicable (no scoped policies for this configuration).") == 2
    release_from_fixtures.assert_not_called()


@pytest.mark.parametrize("flags", [
    ["--skip-release-check", "--release-image", "quay.io/example/release:1"],
    ["--skip-release-check", "--credentials-requests-dir", str(FIXTURES)],
    ["--release-image", "quay.io/example/release:1", "--credentials-requests-dir", str(FIXTURES)],
], ids=["skip+image", "skip+dir", "image+dir"])
def test_conflicting_release_flags_exit_2(tmp_path, flags, release_from_fixtures):
    with pytest.raises(SystemExit) as exc:
        main(_aws_args(tmp_path, "rc12", *flags))
    assert exc.value.code == 2
    assert not (tmp_path / "rc12").exists()
    release_from_fixtures.assert_not_called()


def test_release_check_runs_after_kustomize_validation(tmp_path, release_from_fixtures):
    order = mock.Mock()
    order.attach_mock(release_from_fixtures, "extract")
    kustomize = mock.Mock(return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""))
    order.attach_mock(kustomize, "kustomize")
    args = [a for a in _aws_args(tmp_path, "rc13") if a != "--skip-validation"]
    with mock.patch("scaffold.cli.shutil.which", return_value="/usr/bin/kustomize"), \
            mock.patch("scaffold.cli.subprocess.run", kustomize):
        assert main(args) == 0
    assert [name for name, *_ in order.mock_calls] == ["kustomize", "kustomize", "extract"]


def test_kustomize_failure_short_circuits_release_check(tmp_path, release_from_fixtures):
    args = [a for a in _aws_args(tmp_path, "rc14") if a != "--skip-validation"]
    failed = subprocess.CompletedProcess([], 1, stdout="", stderr="error")
    with mock.patch("scaffold.cli.shutil.which", return_value="/usr/bin/kustomize"), \
            mock.patch("scaffold.cli.subprocess.run", return_value=failed):
        assert main(args) == 1
    release_from_fixtures.assert_not_called()


def test_help_lists_release_flags(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["aws", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--release-image", "--credentials-requests-dir", "--skip-release-check"):
        assert flag in out
