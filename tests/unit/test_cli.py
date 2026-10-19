import subprocess
from unittest import mock

import pytest
import yaml

from scaffold.cli import main


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
