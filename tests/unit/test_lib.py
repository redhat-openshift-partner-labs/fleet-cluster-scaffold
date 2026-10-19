import os

import pytest
import yaml

from scaffold.lib import (
    ClusterParams,
    _resolve_base_resource_path,
    generate_crossplane_patches,
    generate_hive_patches,
    generate_metadata,
    get_default_zones,
    validate_cluster_name,
    validate_profile,
    write_cluster_dir,
)


# ===================== get_default_zones tests =====================


class TestGetDefaultZones:
    def test_us_east_1(self):
        zones = get_default_zones("us-east-1")
        assert zones == ["us-east-1a", "us-east-1b", "us-east-1c"]

    def test_us_east_2(self):
        zones = get_default_zones("us-east-2")
        assert zones == ["us-east-2a", "us-east-2b", "us-east-2c"]

    def test_eu_west_1(self):
        zones = get_default_zones("eu-west-1")
        assert zones == ["eu-west-1a", "eu-west-1b", "eu-west-1c"]


# ===================== generate_hive_patches tests =====================


class TestGenerateHivePatches:
    def test_returns_all_expected_files(self, params):
        patches = generate_hive_patches(params)
        expected_files = {
            "kustomization.yaml",
            "patches/clusterdeployment.yaml",
            "patches/install-config.yaml",
            "patches/install-config-meta.yaml",
            "patches/klusterletaddonconfig.yaml",
            "patches/machinepool-worker.yaml",
            "patches/managedcluster.yaml",
            "patches/namespace.yaml",
        }
        assert set(patches.keys()) == expected_files

    def test_kustomization_namespace(self, params):
        patches = generate_hive_patches(params)
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["namespace"] == "my-cluster"

    def test_kustomization_uses_custom_base_path(self, params):
        patches = generate_hive_patches(params, hive_base_path="../../../cluster-templates/aws/standard/hive")
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["resources"] == ["../../../cluster-templates/aws/standard/hive"]

    def test_kustomization_default_base_path(self, params):
        patches = generate_hive_patches(params)
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["resources"] == ["../base/hive"]

    def test_clusterdeployment_patch_has_name(self, params):
        patches = generate_hive_patches(params)
        cd = yaml.safe_load(patches["patches/clusterdeployment.yaml"])
        names = [op["value"] for op in cd if op["path"] == "/metadata/name"]
        assert names == ["my-cluster"]

    def test_clusterdeployment_patch_has_region(self, params):
        patches = generate_hive_patches(params)
        cd = yaml.safe_load(patches["patches/clusterdeployment.yaml"])
        regions = [
            op["value"] for op in cd if op["path"] == "/spec/platform/aws/region"
        ]
        assert regions == ["us-east-2"]

    def test_clusterdeployment_patch_has_image_set(self, params):
        patches = generate_hive_patches(params)
        cd = yaml.safe_load(patches["patches/clusterdeployment.yaml"])
        refs = [
            op["value"]
            for op in cd
            if op["path"] == "/spec/provisioning/imageSetRef/name"
        ]
        assert refs == ["img4.21.13-x86-64-appsub"]

    def test_install_config_has_correct_name(self, params):
        patches = generate_hive_patches(params)
        ic_raw = patches["patches/install-config.yaml"]
        ic = yaml.safe_load(ic_raw)
        embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
        assert embedded["metadata"]["name"] == "my-cluster"

    def test_install_config_has_correct_region(self, params):
        patches = generate_hive_patches(params)
        ic = yaml.safe_load(patches["patches/install-config.yaml"])
        embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
        assert embedded["platform"]["aws"]["region"] == "us-east-2"

    def test_install_config_zones_match_region(self, params):
        patches = generate_hive_patches(params)
        ic = yaml.safe_load(patches["patches/install-config.yaml"])
        embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
        cp_zones = embedded["controlPlane"]["platform"]["aws"]["zones"]
        w_zones = embedded["compute"][0]["platform"]["aws"]["zones"]
        assert cp_zones == ["us-east-2a", "us-east-2b", "us-east-2c"]
        assert w_zones == ["us-east-2a", "us-east-2b", "us-east-2c"]

    def test_install_config_has_base_domain(self, params):
        patches = generate_hive_patches(params)
        ic = yaml.safe_load(patches["patches/install-config.yaml"])
        embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
        assert embedded["baseDomain"] == "openshiftpartnerlabs.com"

    def test_install_config_meta_patch(self, params):
        patches = generate_hive_patches(params)
        meta = yaml.safe_load(patches["patches/install-config-meta.yaml"])
        names = [op["value"] for op in meta if op["path"] == "/metadata/name"]
        assert names == ["my-cluster-install-config"]

    def test_managedcluster_has_tier_label(self, params):
        patches = generate_hive_patches(params)
        mc = yaml.safe_load(patches["patches/managedcluster.yaml"])
        tier_ops = [op for op in mc if op["path"] == "/metadata/labels/tier"]
        assert tier_ops[0]["value"] == "virt"

    def test_managedcluster_has_environment_label(self, params):
        patches = generate_hive_patches(params)
        mc = yaml.safe_load(patches["patches/managedcluster.yaml"])
        env_ops = [op for op in mc if op["path"] == "/metadata/labels/environment"]
        assert env_ops[0]["value"] == "development"

    def test_managedcluster_has_name_label(self, params):
        patches = generate_hive_patches(params)
        mc = yaml.safe_load(patches["patches/managedcluster.yaml"])
        name_ops = [op for op in mc if op["path"] == "/metadata/labels/name"]
        assert len(name_ops) == 1
        assert name_ops[0]["value"] == "my-cluster"

    def test_managedcluster_has_region_label(self, params):
        patches = generate_hive_patches(params)
        mc = yaml.safe_load(patches["patches/managedcluster.yaml"])
        region_ops = [op for op in mc if op["path"] == "/metadata/labels/region"]
        assert len(region_ops) == 1
        assert region_ops[0]["value"] == "us-east-2"

    def test_machinepool_has_worker_type(self, params):
        patches = generate_hive_patches(params)
        mp = yaml.safe_load(patches["patches/machinepool-worker.yaml"])
        type_ops = [op for op in mp if op["path"] == "/spec/platform/aws/type"]
        assert type_ops[0]["value"] == "m7i.2xlarge"

    def test_install_config_uses_block_scalar(self, params):
        patches = generate_hive_patches(params)
        raw = patches["patches/install-config.yaml"]
        assert "install-config.yaml: |" in raw

    def test_namespace_patch(self, params):
        patches = generate_hive_patches(params)
        ns = yaml.safe_load(patches["patches/namespace.yaml"])
        assert ns[0]["value"] == "my-cluster"


# ===================== generate_crossplane_patches tests =====================


class TestGenerateCrossplanePatches:
    def test_returns_all_expected_files(self, params):
        patches = generate_crossplane_patches(params)
        expected_files = {
            "kustomization.yaml",
            "patches/user.yaml",
            "patches/policy.yaml",
            "patches/policy-attachment.yaml",
            "patches/access-key.yaml",
        }
        assert set(patches.keys()) == expected_files

    def test_user_patch_has_name(self, params):
        patches = generate_crossplane_patches(params)
        user = yaml.safe_load(patches["patches/user.yaml"])
        assert user[0]["value"] == "my-cluster-ocp-installer"

    def test_policy_patch_has_name(self, params):
        patches = generate_crossplane_patches(params)
        policy = yaml.safe_load(patches["patches/policy.yaml"])
        meta_name = [op for op in policy if op["path"] == "/metadata/name"]
        assert meta_name[0]["value"] == "my-cluster-openshift4installerpolicy"

    def test_kustomization_namespace(self, params):
        patches = generate_crossplane_patches(params)
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["namespace"] == "my-cluster"

    def test_kustomization_uses_custom_base_path(self, params):
        patches = generate_crossplane_patches(params, crossplane_base_path="../../../cluster-templates/aws/standard/crossplane")
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["resources"] == ["../../../cluster-templates/aws/standard/crossplane"]

    def test_kustomization_default_base_path(self, params):
        patches = generate_crossplane_patches(params)
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["resources"] == ["../base/crossplane"]

    def test_user_patch_has_namespace(self, params):
        patches = generate_crossplane_patches(params)
        user = yaml.safe_load(patches["patches/user.yaml"])
        ns_ops = [op for op in user if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_policy_patch_has_namespace(self, params):
        patches = generate_crossplane_patches(params)
        policy = yaml.safe_load(patches["patches/policy.yaml"])
        ns_ops = [op for op in policy if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_policy_attachment_patch_has_namespace(self, params):
        patches = generate_crossplane_patches(params)
        pa = yaml.safe_load(patches["patches/policy-attachment.yaml"])
        ns_ops = [op for op in pa if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_access_key_patch_has_namespace(self, params):
        patches = generate_crossplane_patches(params)
        ak = yaml.safe_load(patches["patches/access-key.yaml"])
        ns_ops = [op for op in ak if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_access_key_namespace(self, params):
        patches = generate_crossplane_patches(params)
        ak = yaml.safe_load(patches["patches/access-key.yaml"])
        ns_ops = [
            op
            for op in ak
            if op["path"] == "/spec/writeConnectionSecretToRef/namespace"
        ]
        assert ns_ops[0]["value"] == "my-cluster"


# ===================== write_cluster_dir tests =====================


class TestWriteClusterDir:
    def test_creates_all_files(self, params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        cluster_dir = tmp_path / "my-cluster"
        assert (cluster_dir / "kustomization.yaml").exists()
        assert (cluster_dir / "hive" / "kustomization.yaml").exists()
        assert (cluster_dir / "hive" / "patches" / "clusterdeployment.yaml").exists()
        assert (cluster_dir / "hive" / "patches" / "install-config.yaml").exists()
        assert (
            cluster_dir / "hive" / "patches" / "install-config-meta.yaml"
        ).exists()
        assert (cluster_dir / "hive" / "patches" / "namespace.yaml").exists()
        assert (
            cluster_dir / "hive" / "patches" / "machinepool-worker.yaml"
        ).exists()
        assert (cluster_dir / "hive" / "patches" / "managedcluster.yaml").exists()
        assert (
            cluster_dir / "hive" / "patches" / "klusterletaddonconfig.yaml"
        ).exists()
        assert (cluster_dir / "crossplane" / "kustomization.yaml").exists()
        assert (cluster_dir / "crossplane" / "patches" / "user.yaml").exists()
        assert (cluster_dir / "crossplane" / "patches" / "policy.yaml").exists()
        assert (
            cluster_dir / "crossplane" / "patches" / "policy-attachment.yaml"
        ).exists()
        assert (
            cluster_dir / "crossplane" / "patches" / "access-key.yaml"
        ).exists()

    def test_no_base_folder_created(self, params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        cluster_dir = tmp_path / "my-cluster"
        assert not (cluster_dir / "base").exists()

    def test_top_level_kustomization(self, params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        kust = yaml.safe_load(
            (tmp_path / "my-cluster" / "kustomization.yaml").read_text()
        )
        assert "crossplane/" in kust["resources"]
        assert "hive/" in kust["resources"]

    def test_hive_kustomization_references_cluster_templates(self, params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        cluster_dir = tmp_path / "my-cluster"
        kust = yaml.safe_load(
            (cluster_dir / "hive" / "kustomization.yaml").read_text()
        )
        resource = kust["resources"][0]
        assert "cluster-templates" in resource
        assert "aws/standard/hive" in resource

    def test_crossplane_kustomization_references_cluster_templates(self, params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        cluster_dir = tmp_path / "my-cluster"
        kust = yaml.safe_load(
            (cluster_dir / "crossplane" / "kustomization.yaml").read_text()
        )
        resource = kust["resources"][0]
        assert "cluster-templates" in resource
        assert "aws/standard/crossplane" in resource

    def test_profile_param_flows_through(self, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        params = ClusterParams(
            name="param-test",
            region="us-west-1",
            tier="test",
            topology="standard",
        )
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        cluster_dir = tmp_path / "param-test"
        assert (cluster_dir / "hive" / "kustomization.yaml").exists()
        assert (cluster_dir / "crossplane" / "kustomization.yaml").exists()

    def test_install_config_uses_params_base_domain(self):
        custom_domain = "custom.example.com"
        params = ClusterParams(
            name="domain-test",
            region="us-east-1",
            tier="virt",
            base_domain=custom_domain,
            topology="standard",
        )
        patches = generate_hive_patches(params)
        ic = yaml.safe_load(patches["patches/install-config.yaml"])
        embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
        assert embedded["baseDomain"] == custom_domain


# ===================== _resolve_base_resource_path tests =====================


class TestResolveBaseResourcePath:
    def test_sibling_directories(self, tmp_path):
        clusters_dir = tmp_path / "clusters"
        tpl_dir = tmp_path / "cluster-templates"
        clusters_dir.mkdir()
        tpl_dir.mkdir()
        result = _resolve_base_resource_path(
            str(clusters_dir / "my-cluster"), "hive", str(tpl_dir), "aws/standard"
        )
        assert result == os.path.join("..", "..", "..", "cluster-templates", "aws", "standard", "hive")

    def test_different_profile(self, tmp_path):
        clusters_dir = tmp_path / "clusters"
        tpl_dir = tmp_path / "cluster-templates"
        clusters_dir.mkdir()
        tpl_dir.mkdir()
        result = _resolve_base_resource_path(
            str(clusters_dir / "my-cluster"), "crossplane", str(tpl_dir), "gcp/standard"
        )
        assert "gcp/standard/crossplane" in result


# ===================== generate_metadata tests =====================


class TestGenerateMetadata:
    def test_empty_when_no_htpasswd(self):
        params = ClusterParams(name="m", region="us-east-1", tier="base")
        result = yaml.safe_load(generate_metadata(params))
        assert result == {}

    def test_includes_htpasswd_when_set(self):
        params = ClusterParams(
            name="m", region="us-east-1", tier="base",
            htpasswd_provider_name="Acme Corp",
        )
        result = yaml.safe_load(generate_metadata(params))
        assert result["htpasswd-provider-name"] == "Acme Corp"


class TestWriteClusterDirMetadata:
    def test_metadata_file_exists(self, params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), params, str(tpl_dir))
        assert (tmp_path / "my-cluster" / "metadata.yaml").exists()

    def test_metadata_contains_htpasswd(self, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        p = ClusterParams(
            name="meta-test", region="us-east-1", tier="base",
            htpasswd_provider_name="TestCo",
        )
        write_cluster_dir(str(tmp_path), p, str(tpl_dir))
        meta = yaml.safe_load(
            (tmp_path / "meta-test" / "metadata.yaml").read_text()
        )
        assert meta["htpasswd-provider-name"] == "TestCo"


# ===================== ClusterParams tests =====================


class TestClusterParams:
    def test_default_zones(self):
        params = ClusterParams(name="z", region="ap-south-1", tier="base")
        assert params.zones == ["ap-south-1a", "ap-south-1b", "ap-south-1c"]

    def test_custom_zones_preserved(self):
        zones = ["us-east-1a", "us-east-1d"]
        params = ClusterParams(name="z", region="us-east-1", tier="base", zones=zones)
        assert params.zones == zones

    def test_profile_attr_available(self):
        params_default = ClusterParams(name="p", region="x", tier="t")
        assert params_default.profile == "aws/standard"

        params_custom = ClusterParams(name="p", region="x", tier="t", topology="sno")
        assert params_custom.profile == "aws/sno"

    def test_base_domain_attr_available(self):
        params = ClusterParams(name="b", region="r", tier="t", base_domain="mydomain.com")
        assert params.base_domain == "mydomain.com"


# ===================== validate_cluster_name tests =====================


class TestValidateClusterName:
    def test_valid_simple(self):
        validate_cluster_name("my-cluster")

    def test_valid_single_char(self):
        validate_cluster_name("a")

    def test_valid_numeric(self):
        validate_cluster_name("cluster-01")

    def test_valid_max_length(self):
        validate_cluster_name("a" * 63)

    def test_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            validate_cluster_name("")

    def test_rejects_uppercase(self):
        with pytest.raises(ValueError):
            validate_cluster_name("My-Cluster")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError):
            validate_cluster_name("my cluster")

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError):
            validate_cluster_name("../../etc")

    def test_rejects_special_chars(self):
        with pytest.raises(ValueError):
            validate_cluster_name("my_cluster!")

    def test_rejects_underscore(self):
        with pytest.raises(ValueError):
            validate_cluster_name("my_cluster")

    def test_rejects_starts_with_hyphen(self):
        with pytest.raises(ValueError):
            validate_cluster_name("-cluster")

    def test_rejects_ends_with_hyphen(self):
        with pytest.raises(ValueError):
            validate_cluster_name("cluster-")

    def test_rejects_too_long(self):
        with pytest.raises(ValueError, match="63"):
            validate_cluster_name("a" * 64)


# ===================== validate_profile tests =====================


class TestValidateProfile:
    def test_accepts_aws_standard(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "aws" / "standard" / "hive"
        tpl.mkdir(parents=True)
        validate_profile("aws/standard", str(tmp_path / "cluster-templates"))

    def test_accepts_aws_compact(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "aws" / "compact" / "hive"
        tpl.mkdir(parents=True)
        validate_profile("aws/compact", str(tmp_path / "cluster-templates"))

    def test_accepts_aws_sno(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "aws" / "sno" / "hive"
        tpl.mkdir(parents=True)
        validate_profile("aws/sno", str(tmp_path / "cluster-templates"))

    def test_accepts_aws_standard_default(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "aws" / "standard" / "hive"
        tpl.mkdir(parents=True)
        validate_profile("aws/standard", str(tmp_path / "cluster-templates"))

    def test_rejects_azure(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "azure" / "standard" / "hive"
        tpl.mkdir(parents=True)
        with pytest.raises(ValueError, match="not supported"):
            validate_profile("azure/standard", str(tmp_path / "cluster-templates"))

    def test_rejects_ibmcloud(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "ibmcloud" / "standard" / "hive"
        tpl.mkdir(parents=True)
        with pytest.raises(ValueError, match="not supported"):
            validate_profile("ibmcloud/standard", str(tmp_path / "cluster-templates"))

    def test_rejects_gcp(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "gcp" / "compact" / "hive"
        tpl.mkdir(parents=True)
        with pytest.raises(ValueError, match="not supported"):
            validate_profile("gcp/compact", str(tmp_path / "cluster-templates"))

    def test_rejects_nonexistent_profile(self, tmp_path):
        tpl = tmp_path / "cluster-templates"
        tpl.mkdir()
        with pytest.raises(ValueError, match="not found"):
            validate_profile("aws/nonexistent", str(tpl))

