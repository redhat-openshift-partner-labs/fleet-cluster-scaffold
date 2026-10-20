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

    def test_clusterdeployment_patch_has_base_domain(self, params):
        params.base_domain = "example.org"
        cd = yaml.safe_load(generate_hive_patches(params)["patches/clusterdeployment.yaml"])
        assert [op["value"] for op in cd if op["path"] == "/spec/baseDomain"] == ["example.org"]

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
    def test_returns_all_expected_files(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        expected_files = {
            "kustomization.yaml",
            "patches/user.yaml",
            "patches/policy.yaml",
            "patches/policy-attachment.yaml",
            "patches/access-key.yaml",
        }
        assert set(patches.keys()) == expected_files

    def test_user_patch_has_name(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        user = yaml.safe_load(patches["patches/user.yaml"])
        assert user[0]["value"] == "my-cluster-ocp-installer"

    def test_policy_patch_has_name(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        policy = yaml.safe_load(patches["patches/policy.yaml"])
        meta_name = [op for op in policy if op["path"] == "/metadata/name"]
        assert meta_name[0]["value"] == "my-cluster-openshift4installerpolicy"

    def test_kustomization_namespace(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["namespace"] == "my-cluster"

    def test_kustomization_uses_custom_base_path(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params, crossplane_base_path="../../../cluster-templates/aws/standard/crossplane")
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["resources"] == ["../../../cluster-templates/aws/standard/crossplane"]

    def test_kustomization_default_base_path(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        kust = yaml.safe_load(patches["kustomization.yaml"])
        assert kust["resources"] == ["../base/crossplane"]

    def test_user_patch_has_namespace(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        user = yaml.safe_load(patches["patches/user.yaml"])
        ns_ops = [op for op in user if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_policy_patch_has_namespace(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        policy = yaml.safe_load(patches["patches/policy.yaml"])
        ns_ops = [op for op in policy if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_policy_attachment_patch_has_namespace(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        pa = yaml.safe_load(patches["patches/policy-attachment.yaml"])
        ns_ops = [op for op in pa if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_access_key_patch_has_namespace(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        ak = yaml.safe_load(patches["patches/access-key.yaml"])
        ns_ops = [op for op in ak if op["path"] == "/metadata/namespace"]
        assert len(ns_ops) == 1
        assert ns_ops[0]["value"] == "my-cluster"

    def test_access_key_namespace(self, legacy_params):
        patches = generate_crossplane_patches(legacy_params)
        ak = yaml.safe_load(patches["patches/access-key.yaml"])
        ns_ops = [
            op
            for op in ak
            if op["path"] == "/spec/writeConnectionSecretToRef/namespace"
        ]
        assert ns_ops[0]["value"] == "my-cluster"


# ===================== write_cluster_dir tests =====================


class TestWriteClusterDir:
    def test_creates_all_files(self, legacy_params, tmp_path):
        tpl_dir = tmp_path / "cluster-templates"
        tpl_dir.mkdir()
        write_cluster_dir(str(tmp_path), legacy_params, str(tpl_dir))
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
    def test_platform_keys_when_no_htpasswd(self):
        params = ClusterParams(name="m", region="us-east-1", tier="base")
        result = yaml.safe_load(generate_metadata(params))
        assert result == {"platform": "aws", "aws-credentials-mode": "scoped"}

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

        params_custom = ClusterParams(name="p", region="eastus", tier="t", cloud="azure", topology="sno")
        assert params_custom.profile == "azure/sno"

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

    def test_accepts_azure(self, tmp_path):
        tpl = tmp_path / "cluster-templates" / "azure" / "standard" / "hive"
        tpl.mkdir(parents=True)
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


# ===================== topology tests =====================


class TestTopologyDefaults:
    @pytest.mark.parametrize("topology,cp,workers", [("standard", 3, 3), ("compact", 3, 0), ("sno", 1, 0)])
    def test_replica_defaults(self, topology, cp, workers):
        p = ClusterParams(name="t", region="us-east-1", tier="base", topology=topology)
        assert (p.control_plane_replicas, p.worker_replicas) == (cp, workers)

    def test_explicit_replicas_win(self):
        p = ClusterParams(name="t", region="us-east-1", tier="base", topology="compact", worker_replicas=2)
        assert p.worker_replicas == 2

    @pytest.mark.parametrize("topology", ["compact", "sno"])
    def test_no_machinepool_without_worker_pool(self, topology):
        p = ClusterParams(name="t", region="us-east-1", tier="base", topology=topology)
        patches = generate_hive_patches(p)
        assert "patches/machinepool-worker.yaml" not in patches
        kinds = [e.get("target", {}).get("kind") for e in yaml.safe_load(patches["kustomization.yaml"])["patches"]]
        assert "MachinePool" not in kinds

    def test_zero_workers_omit_platform(self):
        p = ClusterParams(name="t", region="us-east-1", tier="base", topology="compact")
        ic = yaml.safe_load(generate_hive_patches(p)["patches/install-config.yaml"])
        embedded = yaml.safe_load(ic["stringData"]["install-config.yaml"])
        assert embedded["compute"] == [{"name": "worker", "replicas": 0}]


# ===================== azure tests =====================

SUB_ID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture()
def azure_params():
    return ClusterParams(
        name="az-cluster",
        region="eastus2",
        tier="base",
        cloud="azure",
        provider_options={
            "subscription_id": SUB_ID,
            "base_domain_resource_group": "openshift-dns",
            "cloud_name": "AzurePublicCloud",
        },
    )


def _embedded_ic(patches):
    return yaml.safe_load(yaml.safe_load(patches["patches/install-config.yaml"])["stringData"]["install-config.yaml"])


class TestAzureHivePatches:
    def test_defaults(self, azure_params):
        assert azure_params.zones == ["1", "2", "3"]
        assert azure_params.control_plane_type == "Standard_D8s_v5"
        assert get_default_zones("eastus", cloud="azure") == ["1", "2", "3"]

    def test_clusterdeployment_platform_ops(self, azure_params):
        cd = yaml.safe_load(generate_hive_patches(azure_params)["patches/clusterdeployment.yaml"])
        ops = {op["path"]: op["value"] for op in cd}
        assert ops["/spec/platform/azure/region"] == "eastus2"
        assert ops["/spec/platform/azure/baseDomainResourceGroupName"] == "openshift-dns"
        assert not any("/aws/" in path for path in ops)

    def test_install_config_platform(self, azure_params):
        ic = _embedded_ic(generate_hive_patches(azure_params))
        assert ic["platform"] == {"azure": {
            "baseDomainResourceGroupName": "openshift-dns",
            "cloudName": "AzurePublicCloud",
            "region": "eastus2",
            "resourceGroupName": "az-cluster-rg",
        }}
        assert ic["compute"][0]["platform"]["azure"]["osDisk"]["diskType"] == "Premium_LRS"

    def test_zones_are_strings(self, azure_params):
        azure_params.zones = [1, 2]
        patches = generate_hive_patches(azure_params)
        assert _embedded_ic(patches)["controlPlane"]["platform"]["azure"]["zones"] == ["1", "2"]
        mp = yaml.safe_load(patches["patches/machinepool-worker.yaml"])
        assert {op["path"]: op["value"] for op in mp}["/spec/platform/azure/zones"] == ["1", "2"]


class TestAzureCrossplanePatches:
    def test_returns_all_expected_files(self, azure_params):
        assert set(generate_crossplane_patches(azure_params)) == {
            "kustomization.yaml",
            "patches/resource-group.yaml",
            "patches/application.yaml",
            "patches/service-principal.yaml",
            "patches/client-secret.yaml",
            "patches/role-assignment-contributor.yaml",
            "patches/role-assignment-user-access-admin.yaml",
            "patches/role-assignment-dns-zone-contributor.yaml",
            "patches/role-assignment-reader.yaml",
        }

    def test_role_assignment_scopes(self, azure_params):
        patches = generate_crossplane_patches(azure_params)

        def scope(suffix):
            ops = yaml.safe_load(patches[f"patches/role-assignment-{suffix}.yaml"])
            return {op["path"]: op["value"] for op in ops}["/spec/forProvider/scope"]

        rg = f"/subscriptions/{SUB_ID}/resourceGroups/az-cluster-rg"
        assert scope("contributor") == rg
        assert scope("user-access-admin") == rg
        assert scope("dns-zone-contributor").endswith("/resourceGroups/openshift-dns/providers/Microsoft.Network/dnszones/openshiftpartnerlabs.com")
        assert scope("reader") == f"/subscriptions/{SUB_ID}"

    def test_refs_and_secret_namespace(self, azure_params):
        patches = generate_crossplane_patches(azure_params)
        sp = {op["path"]: op["value"] for op in yaml.safe_load(patches["patches/service-principal.yaml"])}
        pw = {op["path"]: op["value"] for op in yaml.safe_load(patches["patches/client-secret.yaml"])}
        assert sp["/spec/forProvider/clientIdRef/name"] == "az-cluster-ocp-installer"
        assert pw["/spec/forProvider/applicationIdRef/name"] == "az-cluster-ocp-installer"
        assert pw["/spec/writeConnectionSecretToRef/namespace"] == "az-cluster"

    def test_kustomization_targets_scoped_by_group(self, azure_params):
        kust = yaml.safe_load(generate_crossplane_patches(azure_params)["kustomization.yaml"])
        password = [e for e in kust["patches"] if e["target"]["kind"] == "Password"][0]
        assert password["target"]["group"] == "applications.azuread.upbound.io"


class TestAzureValidation:
    def test_rejects_bad_subscription(self, azure_params):
        from scaffold.providers import get_provider

        azure_params.provider_options["subscription_id"] = "nope"
        with pytest.raises(ValueError, match="UUID"):
            get_provider("azure").validate(azure_params)


# ===================== repo template consistency =====================

REPO_TEMPLATES = os.path.join(os.path.dirname(__file__), "..", "..", "cluster-templates")


def _template_resources(path):
    """(kind, name) of every resource in a base directory's kustomization."""
    found = set()
    kust = yaml.safe_load(open(os.path.join(path, "kustomization.yaml"), encoding="utf-8"))
    for res in kust["resources"]:
        with open(os.path.join(path, res), encoding="utf-8") as fh:
            for d in yaml.safe_load_all(fh):
                if d:
                    found.add((d["kind"], d["metadata"]["name"]))
    return found


class TestScopedTemplatesMatchPatches:
    @pytest.mark.parametrize("topology", ["standard", "compact", "sno"])
    def test_every_patch_target_exists_in_base(self, topology):
        p = ClusterParams(name="t1", region="us-east-2", tier="base", topology=topology)
        kust = yaml.safe_load(generate_crossplane_patches(p)["kustomization.yaml"])
        targets = {(e["target"]["kind"], e["target"]["name"]) for e in kust["patches"]}
        base = _template_resources(os.path.join(REPO_TEMPLATES, "aws", topology, "crossplane-scoped"))
        assert targets == base

    @pytest.mark.parametrize("topology", ["standard", "compact", "sno"])
    def test_legacy_patch_targets_exist_in_legacy_base(self, topology, legacy_params):
        legacy_params.topology = topology
        kust = yaml.safe_load(generate_crossplane_patches(legacy_params)["kustomization.yaml"])
        targets = {(e["target"]["kind"], e["target"]["name"]) for e in kust["patches"]}
        assert targets <= _template_resources(os.path.join(REPO_TEMPLATES, "aws", topology, "crossplane"))
