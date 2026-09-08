"""Pure validation and profile resolution for cluster configuration."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

Profile = Literal["aws/sno", "aws/compact", "aws/standard"]
Tier = Literal["base", "virt", "ai"]


@dataclass(frozen=True)
class ProfilePolicy:
    control_plane_replicas: int
    worker_replicas: int
    post_install_workers: int = 0


PROFILE_POLICIES: dict[Profile, ProfilePolicy] = {
    "aws/sno": ProfilePolicy(1, 0),
    "aws/compact": ProfilePolicy(1, 0, 1),
    "aws/standard": ProfilePolicy(3, 3),
}


def get_default_zones(region: str) -> list[str]:
    return [f"{region}a", f"{region}b", f"{region}c"]


_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def validate_cluster_name(name: str) -> None:
    """Validate that *name* is a valid DNS-1123 label (RFC 1123).

    Raises ValueError if invalid.
    """
    if not name:
        raise ValueError("Cluster name must not be empty.")
    if len(name) > 63:
        raise ValueError(
            f"Cluster name must be at most 63 characters, got {len(name)}."
        )
    if not _DNS_LABEL_RE.fullmatch(name):
        raise ValueError(
            f"Cluster name {name!r} is not a valid DNS-1123 label. "
            "Use only lowercase letters, digits, and hyphens; "
            "must start and end with an alphanumeric character."
        )



ReplicaCount = Annotated[int, Field(strict=True, ge=0)]


class ClusterParams(BaseModel):
    """Validated parameters; generators treat instances and their zones as read-only."""

    model_config = ConfigDict(extra="forbid", validate_default=True, frozen=True)

    name: str
    region: str
    tier: Tier
    environment: str = "development"
    base_domain: str = "openshiftpartnerlabs.com"
    profile: Profile = "aws/standard"
    control_plane_type: str = "m7i.4xlarge"
    worker_type: str = "m7i.2xlarge"
    control_plane_replicas: ReplicaCount = Field(default_factory=lambda data: PROFILE_POLICIES[data["profile"]].control_plane_replicas)
    worker_replicas: ReplicaCount = Field(default_factory=lambda data: PROFILE_POLICIES[data["profile"]].worker_replicas)
    image_set: str = "img4.21.13-x86-64-appsub"
    zones: list[str] = Field(default_factory=lambda data: get_default_zones(data["region"]))
    htpasswd_provider_name: str | None = None

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        validate_cluster_name(value)
        return value

    @field_validator("control_plane_type", "worker_type")
    @classmethod
    def nonblank_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instance type must not be blank")
        return value

    @field_validator("control_plane_replicas")
    @classmethod
    def fixed_control_plane(cls, value: int, info: ValidationInfo) -> int:
        return _fixed_replicas(value, info, "control_plane_replicas")

    @field_validator("worker_replicas")
    @classmethod
    def fixed_workers(cls, value: int, info: ValidationInfo) -> int:
        return _fixed_replicas(value, info, "worker_replicas")

    @field_validator("zones", mode="before")
    @classmethod
    def default_zones(cls, value: object, info: ValidationInfo) -> object:
        if value is None and "region" in info.data:
            return get_default_zones(info.data["region"])
        return value

    @field_validator("zones")
    @classmethod
    def nonempty_zones(cls, value: list[str]) -> list[str]:
        if not value or any(not zone.strip() for zone in value):
            raise ValueError("zones must be a nonempty list without blank entries")
        return value

    @property
    def policy(self) -> ProfilePolicy:
        return PROFILE_POLICIES[self.profile]


def _fixed_replicas(value: int, info: ValidationInfo, field: str) -> int:
    profile = info.data.get("profile")
    if profile is not None:
        required = getattr(PROFILE_POLICIES[profile], field)
        if value != required:
            raise ValueError(f"profile {profile}: supplied {value}, required {required}")
    return value
