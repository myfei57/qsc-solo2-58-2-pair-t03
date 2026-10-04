"""A masking policy binding datasets to rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PolicyState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"

    @property
    def is_serving(self) -> bool:
        return self is PolicyState.ACTIVE


@dataclass(frozen=True)
class Policy:
    identifier: str
    datasets: tuple[str, ...]
    rules: tuple[str, ...]
    state: str = PolicyState.DRAFT.value
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("policy identifier is required")
        if not self.datasets:
            raise ValueError("policy must target at least one dataset")
        if len(set(self.datasets)) != len(self.datasets):
            raise ValueError("policy datasets must not contain duplicates")
        if not self.rules:
            raise ValueError("policy must reference at least one rule")
        if len(set(self.rules)) != len(self.rules):
            raise ValueError("policy rules must not contain duplicates")
        if self.state not in {item.value for item in PolicyState}:
            raise ValueError(f"unknown policy state {self.state!r}")
        if self.snapshot_id is not None and not self.snapshot_id.strip():
            raise ValueError("policy snapshot id cannot be blank")

    @property
    def state_enum(self) -> PolicyState:
        return PolicyState(self.state)

    def with_state(self, state: PolicyState) -> "Policy":
        return Policy(
            identifier=self.identifier,
            datasets=self.datasets,
            rules=self.rules,
            state=state.value,
            snapshot_id=self.snapshot_id,
        )

    def with_snapshot(self, snapshot_id: str | None) -> "Policy":
        return Policy(
            identifier=self.identifier,
            datasets=self.datasets,
            rules=self.rules,
            state=self.state,
            snapshot_id=snapshot_id,
        )

    def covers(self, dataset: str) -> bool:
        return dataset in self.datasets

    def as_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "datasets": list(self.datasets),
            "rules": list(self.rules),
            "state": self.state,
            "snapshot_id": self.snapshot_id,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "Policy | None":
        if not isinstance(payload, dict):
            return None
        identifier = payload.get("identifier")
        datasets = payload.get("datasets")
        rules = payload.get("rules")
        state = payload.get("state", PolicyState.DRAFT.value)
        snapshot_id = payload.get("snapshot_id")
        if not isinstance(identifier, str) or not isinstance(state, str):
            return None
        if not isinstance(datasets, list) or not isinstance(rules, list):
            return None
        if snapshot_id is not None and not isinstance(snapshot_id, str):
            return None
        try:
            return cls(
                identifier=identifier,
                datasets=tuple(str(item) for item in datasets),
                rules=tuple(str(item) for item in rules),
                state=state,
                snapshot_id=snapshot_id.strip() if isinstance(snapshot_id, str) else None,
            )
        except ValueError:
            return None
