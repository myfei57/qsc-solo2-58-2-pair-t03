"""Deterministic adjudication when several rules match one field."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from maskhub.rule.rule import Rule


@dataclass(frozen=True)
class RankedRule:
    rule_id: str
    priority: int
    specificity: int
    literal_chars: int
    stars: int
    questions: int
    character_classes: int
    enabled: bool

    @classmethod
    def from_rule(cls, rule: Rule) -> "RankedRule":
        score = rule.specificity()
        return cls(
            rule_id=rule.identifier,
            priority=rule.priority,
            specificity=score.score,
            literal_chars=score.literal_chars,
            stars=score.stars,
            questions=score.questions,
            character_classes=score.character_classes,
            enabled=rule.enabled,
        )

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RuleDecision:
    field: str
    selected_rule: str | None
    reason: str
    candidates: tuple[RankedRule, ...]
    ignored: tuple[RankedRule, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "selected_rule": self.selected_rule,
            "reason": self.reason,
            "candidates": [item.as_dict() for item in self.candidates],
            "ignored": [item.as_dict() for item in self.ignored],
        }


def adjudicate(field_name: str, rules: list[Rule] | tuple[Rule, ...]) -> RuleDecision:
    """Return the unique active match and explain every other active match."""

    matches = tuple(
        sorted(
            (RankedRule.from_rule(rule) for rule in rules if rule.pattern_matches(field_name)),
            key=lambda item: (-item.priority, -item.specificity, item.rule_id),
        )
    )
    enabled = tuple(item for item in matches if item.enabled)
    ignored = tuple(item for item in matches if not item.enabled)
    if not enabled:
        if ignored:
            reason = "all matching rules are disabled"
        else:
            reason = "no enabled rule matches"
        return RuleDecision(
            field=field_name,
            selected_rule=None,
            reason=reason,
            candidates=(),
            ignored=ignored,
        )

    winner = enabled[0]
    candidates = tuple(item for item in enabled if item.rule_id != winner.rule_id)
    return RuleDecision(
        field=field_name,
        selected_rule=winner.rule_id,
        reason=_winner_reason(winner, candidates),
        candidates=(winner,) + candidates,
        ignored=ignored,
    )


def _winner_reason(winner: RankedRule, losers: tuple[RankedRule, ...]) -> str:
    if not losers:
        return "only one enabled rule matched"

    lower_priority = tuple(item for item in losers if item.priority < winner.priority)
    same_priority = tuple(item for item in losers if item.priority == winner.priority)
    less_specific = tuple(item for item in same_priority if item.specificity < winner.specificity)
    tied = tuple(item for item in same_priority if item.specificity == winner.specificity)

    parts = []
    if lower_priority:
        parts.append(f"higher priority than {_ids(lower_priority)}")
    if less_specific:
        parts.append(f"more specific than {_ids(less_specific)}")
    if tied:
        parts.append(f"lexicographically smallest identifier among tied rules {_ids(tied)}")
    return "; ".join(parts)


def _ids(items: tuple[RankedRule, ...]) -> str:
    return ", ".join(item.rule_id for item in items)
