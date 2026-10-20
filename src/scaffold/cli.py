"""Scaffold a new cluster overlay directory.

CLI: fleet-scaffold-cluster CLOUD --name NAME --region REGION --tier TIER [options]
Generates <base-path>/<name>/ with all Kustomize patches pre-populated.
Validates output with kustomize build. Exits 1 on validation failure.
"""

from __future__ import annotations

import argparse
import logging
import os.path
import shutil
import subprocess
import sys

from scaffold.lib import (
    TOPOLOGY_REPLICAS,
    ClusterParams,
    find_unpatched,
    validate_cluster_name,
    validate_profile,
    write_cluster_dir,
)
from scaffold.providers import PROVIDERS

_LOG = logging.getLogger("scaffold")


def check_kustomize() -> bool:
    """Return True if kustomize is on PATH, False otherwise."""
    if shutil.which("kustomize") is None:
        _LOG.error(
            "kustomize not found on PATH. Install it before scaffolding."
        )
        return False
    return True


def _common_parser() -> argparse.ArgumentParser:
    """Flags shared by every cloud subcommand."""
    common = argparse.ArgumentParser(add_help=False)

    common.add_argument("--name", required=True, help="Cluster name (DNS-1123 label)")
    common.add_argument("--region", required=True, help="Cloud region (e.g. us-east-1, eastus)")
    common.add_argument("--tier", required=True, choices=["base", "virt", "ai"], help="Tier")
    common.add_argument(
        "--topology",
        default="standard",
        choices=list(TOPOLOGY_REPLICAS),
        help="Cluster topology; selects cluster-templates/<cloud>/<topology> (default: %(default)s)",
    )
    common.add_argument("--environment", default="development", help="Environment name (default: %(default)s)")
    common.add_argument(
        "--base-domain", default="openshiftpartnerlabs.com", help="Cluster base DNS domain (default: %(default)s)"
    )

    # Replica defaults depend on topology (see TOPOLOGY_REPLICAS)
    common.add_argument("--control-plane-replicas", type=int, default=None, help="Default: 3, or 1 for sno")
    common.add_argument("--worker-replicas", type=int, default=None, help="Default: 3, or 0 for compact/sno")

    common.add_argument("--image-set", default="img4.21.13-x86-64-appsub", help="ClusterImageSet name (default: %(default)s)")
    common.add_argument(
        "--install-attempts-limit",
        type=int,
        default=1,
        help="Hive install attempts before the ClusterDeployment fails (default: %(default)s)",
    )
    common.add_argument("--zones", default=None, help="Comma-separated zone list (default: provider-specific)")
    common.add_argument(
        "--htpasswd-provider-name",
        default=None,
        help="Display name for the htpasswd identity provider (should be the company name)",
    )
    common.add_argument("--base-path", default=".", help="Parent directory for cluster overlays (default: %(default)s)")
    common.add_argument(
        "--cluster-templates-dir",
        default="cluster-templates",
        help="Path to the shared cluster-templates directory (default: %(default)s)",
    )
    common.add_argument(
        "--force", action="store_true", default=False, help="Overwrite existing cluster directory if it exists."
    )
    common.add_argument(
        "--skip-validation", action="store_true", default=False, help="Skip kustomize build validation after scaffolding."
    )
    return common


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fleet-scaffold-cluster", description="Scaffold a new cluster overlay")
    sub = parser.add_subparsers(dest="cloud", required=True, metavar="CLOUD")
    common = _common_parser()

    for name, provider in PROVIDERS.items():
        if not provider.implemented:
            # Visible in --help; exits with "not yet supported" before flag parsing matters
            sub.add_parser(name, help=provider.help)
            continue
        p = sub.add_parser(name, parents=[common], help=provider.help)
        # Instance-type defaults differ per cloud, so they're added per subcommand
        p.add_argument(
            "--control-plane-type", default=provider.control_plane_type, help="Control plane instance type (default: %(default)s)"
        )
        p.add_argument("--worker-type", default=provider.worker_type, help="Worker instance type (default: %(default)s)")
        provider.add_arguments(p)
    return parser


def main(args=None) -> int:  # pylint: disable=too-many-return-statements
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = build_parser()
    parsed, extra = parser.parse_known_args(args)

    provider = PROVIDERS[parsed.cloud]
    if not provider.implemented:
        _LOG.error("Cloud provider %r is not yet supported.", parsed.cloud)
        return 1
    if extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")

    try:
        validate_cluster_name(parsed.name)
        if parsed.install_attempts_limit < 1:
            raise ValueError("--install-attempts-limit must be at least 1.")
        params = ClusterParams(
            name=parsed.name,
            region=parsed.region,
            tier=parsed.tier,
            cloud=parsed.cloud,
            topology=parsed.topology,
            environment=parsed.environment,
            base_domain=parsed.base_domain,
            control_plane_type=parsed.control_plane_type,
            worker_type=parsed.worker_type,
            control_plane_replicas=parsed.control_plane_replicas,
            worker_replicas=parsed.worker_replicas,
            image_set=parsed.image_set,
            zones=parsed.zones.split(",") if parsed.zones else None,
            htpasswd_provider_name=parsed.htpasswd_provider_name,
            install_attempts_limit=parsed.install_attempts_limit,
            provider_options=provider.options_from_args(parsed),
        )
        provider.validate(params)
        validate_profile(params.profile, parsed.cluster_templates_dir)
    except ValueError as exc:
        _LOG.error("%s", exc)
        return 1

    cluster_dir = os.path.join(parsed.base_path, parsed.name)
    if os.path.exists(cluster_dir) and not parsed.force:
        _LOG.error(
            "Directory %s already exists. Use --force to overwrite.", cluster_dir
        )
        return 1

    _LOG.info("Scaffolding %s cluster %r in %s/", params.profile, params.name, parsed.base_path)
    cluster_dir = write_cluster_dir(parsed.base_path, params, parsed.cluster_templates_dir)
    _LOG.info("  -> wrote %s", cluster_dir)

    if parsed.skip_validation:
        _LOG.info("Skipping kustomize validation (--skip-validation).")
        return 0

    if not check_kustomize():
        return 1

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
            return 1
        leftover = find_unpatched(result.stdout)
        if leftover:
            _LOG.error(
                "kustomize build %s left base-template names unpatched: %s. The overlay patches do not match "
                "the base in %s (stale cluster-templates?).",
                path, ", ".join(leftover), os.path.join(parsed.cluster_templates_dir, params.profile),
            )
            return 1
        _LOG.info("  -> %s: OK", subdir)

    _LOG.info("Cluster %r scaffolded successfully", params.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
