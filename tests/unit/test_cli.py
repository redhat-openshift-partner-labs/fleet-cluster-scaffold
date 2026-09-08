import shutil
from pathlib import Path
import subprocess
from unittest import mock

import pytest
import yaml

from scaffold.cli import main


@pytest.fixture()
def default_args(tmp_path):
    """Return a list of CLI arguments for the standard scaffold command."""
    tpl_dir = tmp_path / "cluster-templates"
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    return [
        "--name",
        "my-cluster",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--profile",
        "aws/standard",
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    args = [
        "--name",
        "test-01",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--profile",
        "aws/standard",
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    args = [
        "--name",
        "bad-cluster",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--profile",
        "aws/standard",
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    args = [
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
        "--profile",
        "aws/standard",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    main(args)
    assert (tmp_path / "zoned" / "kustomization.yaml").exists()


# ======== NEW tests for new features ========

@mock.patch("scaffold.cli.shutil.which")
def test_shows_kustomize_missing_error(mock_which, tmp_path):
    mock_which.return_value = None
    tpl_dir = tmp_path / "cluster-templates"
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    args = [
        "--name",
        "no-kust",
        "--region",
        "us-east-1",
        "--tier",
        "base",
        "--environment",
        "development",
        "--profile",
        "aws/standard",
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    main([
        "--name", "x",
        "--region", "r",
        "--tier", "base",
        "--environment", "dev",
        "--profile", "aws/standard",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    mock_which.assert_not_called()



@mock.patch("scaffold.cli.subprocess.run")
def test_worker_type_used_verbatim_without_profile(mock_run, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    tpl_dir = tmp_path / "cluster-templates"
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    with mock.patch("scaffold.cli.shutil.which", return_value="kustomize"):
        main([
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    with mock.patch("scaffold.cli.shutil.which", return_value="kustomize"):
        main([
            "--name", "wt2",
            "--region", "us-east-1",
            "--tier", "base",
            "--worker-type", "r6i.xlarge",
            "--profile", "aws/standard",
            "--base-path", str(tmp_path),
            "--cluster-templates-dir", str(tpl_dir),
        ])
    mp = yaml.safe_load((tmp_path / "wt2" / "hive" / "patches" / "machinepool-worker.yaml").read_text())
    type_ops = [op for op in mp if op["path"] == "/spec/platform/aws/type"]
    assert type_ops[0]["value"] == "r6i.xlarge"


def test_base_domain_forwarded_to_output(tmp_path):
    tpl_dir = tmp_path / "cluster-templates"
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    main([
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    main([
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    main([
        "--name", "pf",
        "--region", "us-east-1",
        "--tier", "base",
        "--profile", "aws/standard",
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    (tmp_path / "existing").mkdir()
    result = main([
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    (tmp_path / "existing").mkdir()
    result = main([
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
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", tpl_dir)
    result = main([
        "--name", "fresh",
        "--region", "us-east-1",
        "--tier", "base",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    assert result == 0
    assert (tmp_path / "fresh" / "kustomization.yaml").exists()


def test_rejects_non_aws_profile(tmp_path):
    tpl_dir = tmp_path / "cluster-templates" / "azure" / "standard" / "hive"
    tpl_dir.mkdir(parents=True)
    result = main([
        "--name", "az-cluster",
        "--region", "eastus",
        "--tier", "base",
        "--profile", "azure/standard",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tmp_path / "cluster-templates"),
        "--skip-validation",
    ])
    assert result == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


@pytest.mark.parametrize("option,value", [
    ("--control-plane-replicas", "7"), ("--worker-replicas", "-1"),
    ("--worker-type", " "), ("--zones", "a,,b"), ("--zones", ""),
    ("--profile", "aws/unknown"), ("--tier", "test"), ("--name", "INVALID"),
])
@pytest.mark.parametrize("existing", [False, True])
def test_invalid_configuration_never_writes(default_args, tmp_path, caplog, option, value, existing):
    cluster = tmp_path / "my-cluster"
    if existing:
        cluster.mkdir()
        (cluster / "kustomization.yaml").write_text("keep me\n")
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main(default_args + [option, value, "--force", "--skip-validation"]) == 1
    assert {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before
    assert option in caplog.text


def test_cli_normalizes_zones(default_args, tmp_path):
    assert main(default_args + ["--zones", " custom-z, custom-a ", "--skip-validation"]) == 0
    secret = yaml.safe_load((tmp_path / "my-cluster/hive/patches/install-config.yaml").read_text())
    config = yaml.safe_load(secret["stringData"]["install-config.yaml"])
    assert config["controlPlane"]["platform"]["aws"]["zones"] == ["custom-z", "custom-a"]


def test_missing_required_base_never_writes(default_args, tmp_path):
    (tmp_path / "cluster-templates/aws/standard/hive/kustomization.yaml").unlink()
    assert main(default_args + ["--skip-validation"]) == 1
    assert not (tmp_path / "my-cluster").exists()
