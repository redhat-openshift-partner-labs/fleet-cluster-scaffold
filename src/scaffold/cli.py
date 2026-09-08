"""Scaffold a new cluster overlay directory.

CLI: fleet-scaffold-cluster --name NAME --region REGION --tier TIER [options]
Generates clusters/<name>/ with all Kustomize patches pre-populated.
Validates output with kustomize build. Exits 1 on validation failure.
"""

from __future__ import annotations

import argparse
import logging
import os.path
import shutil
import subprocess
import sys

from pydantic import ValidationError

from scaffold.lib import ClusterParams, validate_template_bases, write_cluster_dir

_LOG = logging.getLogger("scaffold")


def check_kustomize() -> bool:
    """Return True if kustomize is on PATH, False otherwise."""
    if shutil.which("kustomize") is None:
        _LOG.error(
            "kustomize not found on PATH. Install it before scaffolding."
        )
        return False
    return True


def main(args=None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new cluster overlay")

    # Required args (from monorepo CLI — kept verbatim after transport into cli.py context)
    parser.add_argument("--name", required=True, help="Cluster name")
    parser.add_argument("--region", required=True, help="AWS region")
    parser.add_argument(
        "--tier", required=True, help="Tier"
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
        "--control-plane-replicas", type=int, default=None,
    )
    parser.add_argument("--worker-replicas", type=int, default=None)

    # Image set
    parser.add_argument("--image-set", default="img4.21.13-x86-64-appsub")

    # Zones override
    parser.add_argument("--zones", default=None, help="Comma-separated AZ list")

    # Base output dir (overridden from monorepo "clusters" default so this tool works standalone)
    parser.add_argument(
        "--base-path", default=".", help="Parent directory for cluster overlays"
    )

    # NEW: AWS profile mapping to worker type convention
    parser.add_argument("--profile", default=None, help="AWS topology profile")

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

    # Overwrite protection
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing cluster directory if it exists.",
    )

    # Kustomize validation
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        default=False,
        help="Skip kustomize build validation after scaffolding.",
    )

    parsed = parser.parse_args(args)

    zones = [zone.strip() for zone in parsed.zones.split(",")] if parsed.zones is not None else None

    kwargs = dict(
        name=parsed.name,
        region=parsed.region,
        tier=parsed.tier,
        environment=parsed.environment,
        control_plane_type=parsed.control_plane_type,
        worker_type=parsed.worker_type,
        image_set=parsed.image_set,
        zones=zones,
        htpasswd_provider_name=parsed.htpasswd_provider_name,
    )
    if parsed.base_domain is not None:
        kwargs["base_domain"] = parsed.base_domain
    if parsed.profile is not None:
        kwargs["profile"] = parsed.profile
    for field in ("control_plane_replicas", "worker_replicas"):
        value = getattr(parsed, field)
        if value is not None:
            kwargs[field] = value
    try:
        params = ClusterParams(**kwargs)
    except ValidationError as exc:
        for error in exc.errors():
            option = "--" + str(error["loc"][0]).replace("_", "-")
            _LOG.error("%s: %s", option, error["msg"])
        return 1

    try:
        validate_template_bases(params.profile, parsed.cluster_templates_dir)
    except ValueError as exc:
        _LOG.error("%s", exc)
        return 1

    cluster_dir = os.path.join(parsed.base_path, parsed.name)
    if os.path.exists(cluster_dir) and not parsed.force:
        _LOG.error(
            "Directory %s already exists. Use --force to overwrite.", cluster_dir
        )
        return 1

    _LOG.info("Scaffolding cluster %r in %s/", params.name, parsed.base_path)
    cluster_dir = write_cluster_dir(parsed.base_path, params, parsed.cluster_templates_dir)
    _LOG.info("  -> wrote %s", cluster_dir)

    if parsed.skip_validation:
        _LOG.info("Skipping kustomize validation (+skip-validation).")
        return 0

    if not check_kustomize():
        return 1

    # Validate install aggregation and each independent entry point.
    subdirs = [".", "hive", "crossplane"]
    if params.policy.post_install_workers:
        subdirs.append("post-install")
    for subdir in subdirs:
        path = os.path.join(cluster_dir, subdir)
        result = subprocess.run(
            ["kustomize", "build", path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _LOG.error("kustomize build %s failed: %s", path, result.stderr)
            return 1
        _LOG.info("  -> %s: OK", subdir)

    _LOG.info("Cluster %r scaffolded successfully", params.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())