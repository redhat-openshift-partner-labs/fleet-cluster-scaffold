import subprocess
from unittest import mock

import pytest

from scaffold.cli import main


@pytest.fixture()
def default_args(tmp_path):
    """Return a list of CLI arguments for the standard scaffold command."""
    tpl_dir = tmp_path / "cluster-templates"
    tpl_dir.mkdir()
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
        "aws-ha",
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
    tpl_dir.mkdir()
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
        "aws-ha",
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
    tpl_dir.mkdir()
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
        "aws-ha",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    with pytest.raises(SystemExit, match="1"):
        main(args)


@mock.patch("scaffold.cli.shutil.which")
@mock.patch("scaffold.cli.subprocess.run")
def test_scaffold_with_custom_zones(mock_run, mock_which, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        [], returncode=0, stdout="", stderr=""
    )
    mock_which.return_value = "/usr/bin/kustomize"
    tpl_dir = tmp_path / "cluster-templates"
    tpl_dir.mkdir()
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
        "aws-ha",
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
    tpl_dir.mkdir()
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
        "aws-ha",
        "--base-path",
        str(tmp_path),
        "--cluster-templates-dir",
        str(tpl_dir),
    ]
    with pytest.raises(SystemExit) as exc_info:
        main(args)
    assert exc_info.value.code == 1


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
    tpl_dir.mkdir()
    main([
        "--name", "x",
        "--region", "r",
        "--tier", "base",
        "--environment", "dev",
        "--profile", "aws-ha",
        "--base-path", str(tmp_path),
        "--cluster-templates-dir", str(tpl_dir),
        "--skip-validation",
    ])
    mock_which.assert_not_called()


@mock.patch("scaffold.cli.subprocess.run")
def test_no_skip_calls_kustomize_check(mock_run, default_args):
    with mock.patch(
        "scaffold.cli.shutil.which", return_value="kustomize"
    ):
        mock_run.return_value = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
        main(default_args)
    assert mock_run.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
