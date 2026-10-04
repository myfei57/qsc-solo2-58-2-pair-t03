"""Immutable snapshots of the rule set used by a policy activation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from maskhub.errors import NotFound
from maskhub.rule.rule import Rule
from maskhub.store.kvstore import RecordStore

PREFIX = "snapshot."


@dataclass(frozen=True)
class RuleSnapshot:
    identifier: str
    created_at: str
    rules: tuple[Rule, ...]

    def rule(self, identifier: str) -> Rule:
        for rule in self.rules:
            if rule.identifier == identifier:
                return rule
        raise NotFound(f"rule {identifier} is not in snapshot {self.identifier}")

    def as_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "created_at": self.created_at,
            "rules": [rule.as_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "RuleSnapshot | None":
        if not isinstance(payload, dict):
            return None
        identifier = payload.get("identifier")
        created_at = payload.get("created_at")
        raw_rules = payload.get("rules")
        if not isinstance(identifier, str) or not isinstance(created_at, str):
            return None
        if not isinstance(raw_rules, list):
            return None
        rules = tuple(
            item for item in (Rule.from_dict(raw) for raw in raw_rules) if item is not None
        )
        if len(rules) != len(raw_rules):
            return None
        try:
            return cls(identifier=identifier, created_at=created_at, rules=rules)
        except ValueError:
            return None


def canonical_rules(rules: tuple[Rule, ...] | list[Rule]) -> bytes:
    ordered = sorted(rules, key=lambda item: item.identifier)
    return json.dumps(
        [rule.as_dict() for rule in ordered],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def snapshot_identifier(rules: tuple[Rule, ...] | list[Rule]) -> str:
    return hashlib.sha256(canonical_rules(rules)).hexdigest()


def snapshot_key(identifier: str) -> str:
    return PREFIX + identifier


class SnapshotRegistry:
    def __init__(self, store: RecordStore) -> None:
        self._store = store

    def capture(
        self,
        rule_ids: tuple[str, ...] | list[str],
        rules_registry,
        created_at: str | None = None,
    ) -> RuleSnapshot:
        """Resolve current rules and retain an immutable, content-addressed copy."""

        rules = tuple(rules_registry.get(identifier) for identifier in rule_ids)
        identifier = snapshot_identifier(rules)
        existing = self.find(identifier)
        if existing is not None:
            return existing

        snapshot = RuleSnapshot(
            identifier=identifier,
            created_at=created_at
            or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            rules=rules,
        )
        self._store.put_json(snapshot_key(identifier), snapshot.as_dict())
        return snapshot

    def get(self, identifier: str) -> RuleSnapshot:
        snapshot = self.find(identifier)
        if snapshot is None:
            raise NotFound(f"unknown rule snapshot {identifier}")
        return snapshot

    def find(self, identifier: str) -> RuleSnapshot | None:
        return RuleSnapshot.from_dict(self._store.get_json(snapshot_key(identifier)))

    def identifiers(self) -> list[str]:
        from maskhub.store.query import keys_with_prefix

        return [key[len(PREFIX):] for key in keys_with_prefix(self._store, PREFIX)]

    def all(self) -> list[RuleSnapshot]:
        return [self.get(identifier) for identifier in self.identifiers()]
