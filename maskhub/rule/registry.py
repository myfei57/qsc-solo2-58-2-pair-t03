"""Flat registry of masking rules."""

from __future__ import annotations

from maskhub.errors import Conflict, NotFound
from maskhub.rule.adjudication import RuleDecision, adjudicate
from maskhub.rule.rule import Rule
from maskhub.store.kvstore import RecordStore

PREFIX = "rule."


def rule_key(identifier: str) -> str:
    return PREFIX + identifier


class RuleRegistry:
    def __init__(self, store: RecordStore) -> None:
        self._store = store

    def add(self, rule: Rule) -> Rule:
        if self._store.has(rule_key(rule.identifier)):
            raise Conflict(f"rule {rule.identifier} already exists")
        self._store.put_json(rule_key(rule.identifier), rule.as_dict())
        return rule

    def save(self, rule: Rule) -> Rule:
        self._store.put_json(rule_key(rule.identifier), rule.as_dict())
        return rule

    def get(self, identifier: str) -> Rule:
        rule = Rule.from_dict(self._store.get_json(rule_key(identifier)))
        if rule is None:
            raise NotFound(f"unknown rule {identifier}")
        return rule

    def find(self, identifier: str) -> Rule | None:
        return Rule.from_dict(self._store.get_json(rule_key(identifier)))

    def remove(self, identifier: str) -> None:
        if not self._store.has(rule_key(identifier)):
            raise NotFound(f"unknown rule {identifier}")
        self._store.delete(rule_key(identifier))

    def set_enabled(self, identifier: str, enabled: bool) -> Rule:
        rule = self.get(identifier)
        updated = Rule(
            identifier=rule.identifier,
            field_pattern=rule.field_pattern,
            action=rule.action,
            parameters=rule.parameters,
            priority=rule.priority,
            enabled=enabled,
        )
        return self.save(updated)

    def identifiers(self) -> list[str]:
        from maskhub.store.query import keys_with_prefix

        return [key[len(PREFIX):] for key in keys_with_prefix(self._store, PREFIX)]

    def all(self) -> list[Rule]:
        return [self.get(identifier) for identifier in self.identifiers()]

    def matching(self, field_names: list[str]) -> dict[str, list[str]]:
        """Return, for each field, the enabled rules whose pattern matches it."""

        result: dict[str, list[str]] = {}
        for name in field_names:
            hits = [rule.identifier for rule in self.all() if rule.matches(name)]
            if hits:
                result[name] = hits
        return result

    def decisions(self, field_names: list[str]) -> dict[str, RuleDecision]:
        rules = self.all()
        return {name: adjudicate(name, rules) for name in field_names}
