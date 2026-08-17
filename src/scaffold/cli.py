"""Scaffold a new cluster overlay directory.

CLI: fleet-scaffold-cluster --name NAME --region REGION --tier TIER [options]
Generates clusters/<name>/ with all Kustomize patches pre-populated.
Validates output with kustomize build. Exits 1 on validation failure.
"""

import argparse
import logging
import os.path
import shutil
import subprocess
import sys

from scaffold.lib import ClusterParams, write_cluster_dir

_LOG = logging.getLogger("scaffold")


def check_kustomize() -> None:
    """Ensure kustomize is on PATH. Exit 1 with error if missing."""
    if shutil.which("kustomize") is None:
        _LOG.error(
            "kustomize not found on PATH. Install it before scaffolding."
        )
        sys.exit(1)


def main(args=None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new cluster overlay")

    # Required args (from monorepo CLI — kept verbatim after transport into cli.py context)
    parser.add_argument("--name", required=True, help="Cluster name")
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument(
        "--tier", required=True, choices=["base", "virt", "ai"], help="Tier"
    )

    # Environment
    parser.add_argument("--environment", default="development", help="Environment name")

    # Control-plane tuning
    parser.add_argument(
        "--control-plane-type",
        default="m7i.4xlarge",
    )
    parser.add_argument(
        "--worker-type", default="m7i.2xlarge"
    )
    parser.add_argument(
        "--control-plane-replicas", type=int, default=3,
    )
    parser.add_argument("--worker-replicas", type=int, default=3)

    # Image set
    parser.add_argument("--image-set", default="img4.21.13-x86-64-appsub")

    # Zones override
    parser.add_argument("--zones", default=None, help="Comma-separated AZ list")

    # Base output dir (overridden from monorepo "clusters" default so this tool works standalone)
    parser.add_argument(
        "--base-path", default=".", help="Parent directory for cluster overlays"
    )

    # NEW: AWS profile mapping to worker type convention
    parser.add_argument("--profile", default=None, help="AWS profile (maps to worker-type)")

    # NEW: base domain override
    parser.add_argument("--base-domain", default=None, help="Cluster base DNS domain")

    # Cluster metadata
    parser.add_argument(
        "--htpasswd-provider-name",
        default=None,
        help="Display name for the htpasswd identity provider (should be the company name)",
    )

    # Cluster templates directory
    parser.add_argument(
        "--cluster-templates-dir",
        default="cluster-templates",
        help="Path to the shared cluster-templates directory",
    )

    # Kustomize validation
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        default=False,
        help="Skip kustomize build validation after scaffolding.",
    )

    parsed = parser.parse_args(args)

    zones = parsed.zones.split(",") if parsed.zones else None

    params = ClusterParams(
        name=parsed.name,
        region=parsed.region,
        tier=parsed.tier,
        environment=parsed.environment,
        control_plane_type=parsed.control_plane_type,
        worker_type=get_worker_type_from_profile(parsed.worker_type, parsed.profile),
        control_plane_replicas=parsed.control_plane_replicas,
        worker_replicas=parsed.worker_replicas,
        image_set=parsed.image_set,
        zones=zones,
        htpasswd_provider_name=parsed.htpasswd_provider_name,
    )

    _LOG.info("Scaffolding cluster %r in %s/", params.name, parsed.base_path)
    cluster_dir = write_cluster_dir(parsed.base_path, params, parsed.cluster_templates_dir)
    _LOG.info("  -> wrote %s", cluster_dir)

    if parsed.skip_validation:
        _LOG.info("Skipping kustomize validation (+skip-validation).")
        return 0

    check_kustomize()

    # Validate each sub-dir
    for subdir in ["hive", "crossplane"]:
        path = os.path.join(cluster_dir, subdir)
        result = subprocess.run(
            ["kustomize", "build", path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _LOG.error("kustomize build %s failed: %s", path, result.stderr)
            sys.exit(1)
        _LOG.info("  -> %s: OK", subdir)

    _LOG.info("Cluster %r scaffolded successfully", params.name)
    return 0


def get_worker_type_from_profile(worker_type: str, profile: str | None) -> str:
    """Map an AWS profile name to a worker-type preset."""
    overrides = {
        "aws-ha": "m7i.2xlarge",
        "aws-small": "m5.large",
    }
    if profile and profile in overrides:
        return overrides[profile]
    return


entry_point_args = None  # allow test harness to override sys.argv


if __name__ == "__main__":
    sys.exit(main(entry_point_args))