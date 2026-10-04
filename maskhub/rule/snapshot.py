"""Immutable snapshots of the rule set a policy was activated with.

A snapshot freezes the full definitions of the rules a policy referenced at
activation time. Snapshots are content-addressed and create-only: later rule
edits or removals never touch them, so any past result can be explained by
replaying adjudication against the snapshot that was in effect.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from maskhub.errors import Conflict, NotFound
from maskhub.policy.policy import Policy
from maskhub.rule.rule import Rule
from maskhub.store.kvstore import RecordStore

PREFIX = "snapshot."


def snapshot_key(identifier: str) -> str:
    return PREFIX + identifier


def _canonical(policy: str, rules: tuple[Rule, ...]) -> str:
    payload = {
        "policy": policy,
        "rules": [rule.as_dict() for rule in rules],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class RuleSnapshot:
    """A frozen, content-addressed copy of one policy's effective rules."""

    identifier: str
    policy: str
    created_at: str
    digest: str
    rules: tuple[Rule, ...]

    def summary(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "policy": self.policy,
            "created_at": self.created_at,
            "digest": self.digest,
            "rules": len(self.rules),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "policy": self.policy,
            "created_at": self.created_at,
            "digest": self.digest,
            "rules": [rule.as_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "RuleSnapshot | None":
        if not isinstance(payload, dict):
            return None
        identifier = payload.get("identifier")
        policy = payload.get("policy")
        created_at = payload.get("created_at")
        digest = payload.get("digest")
        raw_rules = payload.get("rules")
        if not all(
            isinstance(item, str) for item in (identifier, policy, created_at, digest)
        ):
            return None
        if not isinstance(raw_rules, list):
            return None
        rules = tuple(
            item for item in (Rule.from_dict(raw) for raw in raw_rules) if item is not None
        )
        if len(rules) != len(raw_rules):
            return None
        return cls(
            identifier=identifier,
            policy=policy,
            created_at=created_at,
            digest=digest,
            rules=rules,
        )


class SnapshotRegistry:
    """Create-only snapshot storage: snapshots can be read, never changed."""

    def __init__(self, store: RecordStore) -> None:
        self._store = store

    def capture(self, policy: Policy, rules: Iterable[Rule]) -> RuleSnapshot:
        """Freeze the rules a policy is activated with.

        The identifier derives from the content, so capturing the same rule
        set again returns the existing snapshot untouched.
        """

        frozen = tuple(sorted(rules, key=lambda rule: rule.identifier))
        digest = hashlib.sha256(
            _canonical(policy.identifier, frozen).encode("utf-8")
        ).hexdigest()
        identifier = f"snap-{digest[:16]}"
        existing = self.find(identifier)
        if existing is not None:
            if existing.digest != digest:
                raise Conflict(
                    f"snapshot {identifier} already exists with different content"
                )
            return existing
        snapshot = RuleSnapshot(
            identifier=identifier,
            policy=policy.identifier,
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            digest=digest,
            rules=frozen,
        )
        self._store.put_json(snapshot_key(identifier), snapshot.as_dict())
        return snapshot

    def get(self, identifier: str) -> RuleSnapshot:
        snapshot = self.find(identifier)
        if snapshot is None:
            raise NotFound(f"unknown snapshot {identifier}")
        return snapshot

    def find(self, identifier: str) -> RuleSnapshot | None:
        return RuleSnapshot.from_dict(self._store.get_json(snapshot_key(identifier)))

    def identifiers(self) -> list[str]:
        from maskhub.store.query import keys_with_prefix

        return [key[len(PREFIX):] for key in keys_with_prefix(self._store, PREFIX)]

    def all(self) -> list[RuleSnapshot]:
        return [self.get(identifier) for identifier in self.identifiers()]
