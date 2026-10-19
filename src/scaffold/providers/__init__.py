"""Cloud provider registry. Each entry becomes a CLI subcommand."""

from __future__ import annotations

from scaffold.providers.aws import AWSProvider
from scaffold.providers.azure import AzureProvider
from scaffold.providers.base import PlannedProvider, Provider

# Insertion order is the --help order. Replace a PlannedProvider with a real one to enable it.
PROVIDERS: dict[str, Provider] = {
    p.name: p
    for p in (
        AWSProvider(),
        AzureProvider(),
        PlannedProvider("gcp", "Google Cloud Platform"),
        PlannedProvider("ibmcloud", "IBM Cloud"),
    )
}


def get_provider(cloud: str) -> Provider:
    try:
        return PROVIDERS[cloud]
    except KeyError:
        raise ValueError(f"Unknown cloud provider {cloud!r}. Choose from: {', '.join(PROVIDERS)}.") from None
