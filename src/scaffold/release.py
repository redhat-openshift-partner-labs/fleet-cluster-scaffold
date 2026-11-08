"""CredentialsRequests of an OpenShift release, read from extracted manifests.

The scoped AWS policies in scaffold.providers.aws_policies are hand-written. This module supplies
the release's requirements so aws_policies.coverage_gaps can compare the two: either from a
directory of already extracted manifests, or by running `oc adm release extract` against the
release image named by the hub ClusterImageSet.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
from dataclasses import dataclass

import yaml


class ReleaseError(Exception):
    """Every failure in this module: unreadable or malformed manifests, no CredentialsRequests."""


@dataclass(frozen=True)
class CredentialsRequest:
    """The parts of a CredentialsRequest the scaffold compares against its scoped policies."""

    name: str  # metadata.name
    provider_kind: str  # spec.providerSpec.kind, e.g. AWSProviderSpec
    namespace: str  # spec.secretRef.namespace
    secret: str  # spec.secretRef.name
    actions: tuple[str, ...]  # Allow statements only (effect defaults to Allow), file order, de-duplicated


def _parse(doc: dict) -> CredentialsRequest:
    spec = doc["spec"]
    provider = spec["providerSpec"]
    actions: dict[str, None] = {}  # insertion-ordered set
    for st in provider.get("statementEntries") or ():
        if st.get("effect", "Allow") == "Allow":
            actions.update(dict.fromkeys(st.get("action") or ()))
    return CredentialsRequest(
        name=doc["metadata"]["name"],
        provider_kind=provider["kind"],
        namespace=spec["secretRef"]["namespace"],
        secret=spec["secretRef"]["name"],
        actions=tuple(actions),
    )


def load_credentials_requests(path: str | os.PathLike) -> list[CredentialsRequest]:
    """Parse every CredentialsRequest under ``path``: sorted *.yaml and *.yml files, multi-document.

    Empty documents and other kinds are skipped. Raises ReleaseError when ``path`` is not a
    directory, a file is malformed, or no CredentialsRequest is found.
    """
    root = pathlib.Path(path)
    if not root.is_dir():
        raise ReleaseError(f"{root} is not a directory")
    out: list[CredentialsRequest] = []
    for f in sorted(p for p in root.iterdir() if p.suffix in (".yaml", ".yml")):
        try:
            for doc in yaml.safe_load_all(f.read_text()):
                if isinstance(doc, dict) and doc.get("kind") == "CredentialsRequest":
                    out.append(_parse(doc))
        except (yaml.YAMLError, KeyError, TypeError, AttributeError) as exc:
            raise ReleaseError(f"{f}: malformed CredentialsRequest manifest ({exc})") from exc
    if not out:
        raise ReleaseError(f"no CredentialsRequests found under {root}")
    return out


RELEASE_REPOSITORY = "quay.io/openshift-release-dev/ocp-release"
# Hub ClusterImageSet naming convention: img<major>.<minor>.<patch>-x86-64-appsub
IMAGE_SET_RE = re.compile(r"^img(\d+\.\d+\.\d+)-x86-64-appsub$")
EXTRACT_TIMEOUT = 300  # seconds; a cold extraction takes about 20 s


def release_image_for(image_set: str) -> str:
    """Release pullspec for a ClusterImageSet named by the hub convention."""
    m = IMAGE_SET_RE.match(image_set)
    if not m:
        raise ReleaseError(
            f"cannot derive a release image from image set {image_set!r} (expected img<x.y.z>-x86-64-appsub); "
            "pass --release-image PULLSPEC, or --skip-release-check to scaffold without verification")
    return f"{RELEASE_REPOSITORY}:{m.group(1)}-x86_64"


def extract_credentials_requests(image: str, install_config_yaml: str, cloud: str,
                                 workdir: str) -> list[CredentialsRequest]:
    """Extract the CredentialsRequests the installer would apply for ``image`` and parse them.

    ``--included`` filters by the install-config's capabilities and feature set, so the rendered
    install-config is written to ``<workdir>/install-config.yaml``; the manifests land in
    ``<workdir>/credentials-requests``. The release repository is public, so no pull secret is used.
    """
    if shutil.which("oc") is None:
        raise ReleaseError("oc not found on PATH; install the OpenShift client, "
                           "or pass --credentials-requests-dir DIR or --skip-release-check")
    install_config = os.path.join(workdir, "install-config.yaml")
    to_dir = os.path.join(workdir, "credentials-requests")
    with open(install_config, "w", encoding="utf-8") as fh:
        fh.write(install_config_yaml)
    argv = ["oc", "adm", "release", "extract", "--credentials-requests", f"--cloud={cloud}", "--included",
            f"--install-config={install_config}", f"--to={to_dir}", image]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=EXTRACT_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise ReleaseError(f"oc adm release extract timed out after {EXTRACT_TIMEOUT}s for {image}") from exc
    if proc.returncode != 0:
        raise ReleaseError(f"oc adm release extract failed for {image} (exit {proc.returncode}): {proc.stderr.strip()}")
    return load_credentials_requests(to_dir)
