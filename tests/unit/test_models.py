"""Configuration contract exercised through the public library import."""

import pytest

from scaffold.lib import ClusterParams


def make_params(**kwargs):
    return ClusterParams(**dict(name="cluster-1", region="us-east-1", tier="base") | kwargs)


@pytest.mark.parametrize("profile,cp,workers", [("aws/sno", 1, 0), ("aws/compact", 1, 0), ("aws/standard", 3, 3)])
@pytest.mark.parametrize("tier", ["base", "virt", "ai"])
def test_profile_topology(profile, cp, workers, tier):
    params = make_params(profile=profile, tier=tier)
    assert (params.control_plane_replicas, params.worker_replicas) == (cp, workers)
    assert make_params(profile=profile, control_plane_replicas=cp, worker_replicas=workers) == params.model_copy(update={"tier": "base"})
    assert params.zones == ["us-east-1a", "us-east-1b", "us-east-1c"]


@pytest.mark.parametrize("profile,required", [("aws/sno", 1), ("aws/compact", 1), ("aws/standard", 3)])
def test_conflict_explains_profile_and_values(profile, required):
    with pytest.raises(ValueError, match=rf"{profile}.*7.*{required}"):
        make_params(profile=profile, control_plane_replicas=7)


@pytest.mark.parametrize("field", ["control_plane_replicas", "worker_replicas"])
@pytest.mark.parametrize("value", [True, False, "3", 3.0, 1.5, -1, None])
def test_strict_replica_inputs(field, value):
    with pytest.raises(ValueError):
        make_params(**{field: value})


@pytest.mark.parametrize("kwargs", [
    {"name": name} for name in ["", "A", "a_", "a\n", "../x", "-a", "a-", "a" * 64]
] + [
    {"tier": "test"}, {"profile": "aws"}, {"profile": "aws/other"},
    {"profile": "azure/standard"}, {"unknown": 1},
    {"control_plane_type": " "}, {"worker_type": ""},
    {"zones": []}, {"zones": ["a", " "]}, {"zones": "a,b"},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        make_params(**kwargs)


@pytest.mark.parametrize("profile", ["aws/sno", "aws/compact", "aws/standard"])
def test_arbitrary_types_and_zones(profile):
    params = make_params(profile=profile, control_plane_type="future.large", worker_type="custom.type", zones=["custom-z", "custom-a", "custom-b", "custom-c"])
    assert params.control_plane_type == "future.large"
    assert params.worker_type == "custom.type"
    assert params.zones == ["custom-z", "custom-a", "custom-b", "custom-c"]


def test_defaults_and_public_import():
    from scaffold.models import ClusterParams as Model
    assert Model is ClusterParams
    params = make_params()
    assert params.control_plane_type == "m7i.4xlarge"
    assert params.worker_type == "m7i.2xlarge"
    assert make_params(zones=None).zones == params.zones
