"""Shared fixtures for fleet cluster scaffolder tests."""

import pytest

from scaffold.lib import ClusterParams


@pytest.fixture()
def params():
    return ClusterParams(
        name="my-cluster",
        region="us-east-2",
        tier="virt",
        environment="development",
        base_domain="openshiftpartnerlabs.com",
        topology="standard",
        control_plane_type="m7i.4xlarge",
        worker_type="m7i.2xlarge",
        control_plane_replicas=3,
        worker_replicas=3,
        image_set="img4.21.13-x86-64-appsub",
        zones=["us-east-2a", "us-east-2b", "us-east-2c"],
    )
