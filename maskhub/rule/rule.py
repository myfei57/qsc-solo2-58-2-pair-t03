"""A rule that binds a field pattern to a masking action."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

SUPPORTED_ACTIONS = ("redact", "hash", "partial", "tokenize")
DEFAULT_PRIORITY = 100


@dataclass(frozen=True)
class SpecificityScore:
    score: int
    literal_chars: int
    stars: int
    questions: int
    character_classes: int


@dataclass(frozen=True)
class Rule:
    identifier: str
    field_pattern: str
    action: str
    parameters: dict[str, object] = field(default_factory=dict)
    priority: int = DEFAULT_PRIORITY
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.identifier.strip():
            raise ValueError("rule identifier is required")
        if not self.field_pattern.strip():
            raise ValueError("rule field pattern is required")
        if self.action not in SUPPORTED_ACTIONS:
            raise ValueError(f"unsupported action {self.action!r}")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ValueError("rule priority must be an integer")
        if not isinstance(self.enabled, bool):
            raise ValueError("rule enabled must be a boolean")

    def pattern_matches(self, field_name: str) -> bool:
        return fnmatch.fnmatchcase(field_name.lower(), self.field_pattern.lower())

    def matches(self, field_name: str) -> bool:
        return self.enabled and self.pattern_matches(field_name)

    def specificity(self) -> SpecificityScore:
        """Score literal exactness without reading the registry order.

        Higher is more specific. Exact names beat character classes, which beat
        single-character wildcards, which broadly beat '*' wildcards.
        """

        literal_chars = 0
        stars = 0
        questions = 0
        classes = 0
        index = 0
        pattern = self.field_pattern
        while index < len(pattern):
            char = pattern[index]
            if char == "*":
                stars += 1
            elif char == "?":
                questions += 1
            elif char == "[":
                close = pattern.find("]", index + 1)
                if close > index:
                    classes += 1
                    index = close
                else:
                    literal_chars += len(char)
            else:
                literal_chars += len(char)
            index += 1

        score = (
            literal_chars * 1000
            + classes * 10
            + questions * 5
            - stars * 100
        )
        return SpecificityScore(
            score=score,
            literal_chars=literal_chars,
            stars=stars,
            questions=questions,
            character_classes=classes,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "identifier": self.identifier,
            "field_pattern": self.field_pattern,
            "action": self.action,
            "parameters": self.parameters,
            "priority": self.priority,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, payload: object) -> "Rule | None":
        if not isinstance(payload, dict):
            return None
        identifier = payload.get("identifier")
        pattern = payload.get("field_pattern")
        action = payload.get("action")
        parameters = payload.get("parameters", {})
        priority = payload.get("priority", DEFAULT_PRIORITY)
        enabled = payload.get("enabled", True)
        if not isinstance(identifier, str) or not isinstance(pattern, str):
            return None
        if not isinstance(action, str) or not isinstance(parameters, dict):
            return None
        if not isinstance(priority, int) or isinstance(priority, bool):
            return None
        if not isinstance(enabled, bool):
            return None
        try:
            return cls(
                identifier=identifier,
                field_pattern=pattern,
                action=action,
                parameters=parameters,
                priority=priority,
                enabled=enabled,
            )
        except ValueError:
            return None
