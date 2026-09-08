"""Profile output and actual Kustomize composition regression coverage."""

from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from scaffold.cli import main
from scaffold.lib import ClusterParams, generate_hive_patches, write_cluster_dir

PROFILES = [("aws/sno", 1, 0), ("aws/compact", 1, 0), ("aws/standard", 3, 3)]


@pytest.mark.parametrize("profile,cp,workers", PROFILES)
def test_install_patches(profile, cp, workers):
    params = ClusterParams(name="test", region="r", tier="base", profile=profile)
    patches = generate_hive_patches(params)
    secret = yaml.safe_load(patches["patches/install-config.yaml"])
    config = yaml.safe_load(secret["stringData"]["install-config.yaml"])
    assert config["controlPlane"]["replicas"] == cp
    assert config["compute"][0]["replicas"] == workers
    assert ("patches/machinepool-worker.yaml" in patches) == bool(workers)
    kust = yaml.safe_load(patches["kustomization.yaml"])
    assert any(p["path"] == "patches/machinepool-worker.yaml" for p in kust["patches"]) == bool(workers)


def build(path):
    result = subprocess.run(["kustomize", "build", str(path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return list(yaml.safe_load_all(result.stdout))


@pytest.mark.skipif(shutil.which("kustomize") is None, reason="kustomize unavailable")
@pytest.mark.parametrize("profile,cp,workers", PROFILES)
@pytest.mark.parametrize("explicit", [False, True])
def test_cli_composition_and_determinism(tmp_path, profile, cp, workers, explicit):
    templates = tmp_path / "custom/shared-templates"
    shutil.copytree(Path(__file__).resolve().parents[2] / "cluster-templates", templates)
    output = tmp_path / "elsewhere/nested/clusters"
    args = ["--name", "rendered", "--region", "custom", "--tier", "ai", "--profile", profile,
            "--zones", " zone-z, zone-a ", "--worker-type", "future.worker", "--control-plane-type", "future.master",
            "--base-domain", "custom.example.com", "--htpasswd-provider-name", "Example Co",
            "--base-path", str(output), "--cluster-templates-dir", str(templates)]
    if explicit:
        args += ["--control-plane-replicas", str(cp), "--worker-replicas", str(workers)]
    assert main(args) == 0
    cluster = output / "rendered"
    root = build(cluster)
    hive = build(cluster / "hive")
    crossplane = build(cluster / "crossplane")
    assert len(root) == len(hive) + len(crossplane)
    assert {r["kind"] for r in crossplane} == {"User", "Policy", "UserPolicyAttachment", "AccessKey"}
    assert {r["kind"] for r in hive} == {"Namespace", "Secret", "ClusterDeployment", "ManagedCluster", "KlusterletAddonConfig"} | ({"MachinePool"} if workers else set())
    secret = next(r for r in hive if r["kind"] == "Secret")
    config = yaml.safe_load(secret["stringData"]["install-config.yaml"])
    assert config["controlPlane"]["replicas"] == cp
    assert config["compute"][0]["replicas"] == workers
    assert config["controlPlane"]["platform"]["aws"] == {"type": "future.master", "zones": ["zone-z", "zone-a"]}
    assert config["baseDomain"] == "custom.example.com"
    for subdir in ["hive", "crossplane"] + (["post-install"] if profile == "aws/compact" else []):
        resource = yaml.safe_load((cluster / subdir / "kustomization.yaml").read_text())["resources"][0]
        assert not Path(resource).is_absolute()
        assert (cluster / subdir / resource).resolve() == templates / profile / subdir
    if profile == "aws/compact":
        post = build(cluster / "post-install")
        assert len(post) == 1
        pool = post[0]
        assert pool["kind"] == "MachinePool"
        assert pool["metadata"] == {"name": "rendered-worker", "namespace": "rendered"}
        assert pool["spec"]["replicas"] == 1
        assert pool["spec"]["clusterDeploymentRef"]["name"] == "rendered"
        assert pool["spec"]["platform"]["aws"]["type"] == "future.worker"
        assert pool["spec"]["platform"]["aws"]["zones"] == ["zone-z", "zone-a"]
    else:
        assert not (cluster / "post-install").exists()
    assert yaml.safe_load((cluster / "metadata.yaml").read_text()) == {"htpasswd-provider-name": "Example Co"}
    before = {p.relative_to(cluster): p.read_bytes() for p in cluster.rglob("*") if p.is_file()}
    assert main(args + ["--force"]) == 0
    assert {p.relative_to(cluster): p.read_bytes() for p in cluster.rglob("*") if p.is_file()} == before


def test_profile_change_removes_stale_worker_output(tmp_path):
    for profile in ["aws/standard", "aws/compact", "aws/sno"]:
        params = ClusterParams(name="changing", region="r", tier="base", profile=profile)
        write_cluster_dir(str(tmp_path), params)
    cluster = tmp_path / "changing"
    assert not (cluster / "hive/patches/machinepool-worker.yaml").exists()
    assert not (cluster / "post-install/kustomization.yaml").exists()
