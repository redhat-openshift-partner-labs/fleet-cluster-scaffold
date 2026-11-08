"""CredentialsRequests of an OpenShift release, read from extracted manifests.

The scoped AWS policies in scaffold.providers.aws_policies are hand-written. This module supplies
the release's requirements so aws_policies.coverage_gaps can compare the two.
"""

from __future__ import annotations

import os
import pathlib
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
