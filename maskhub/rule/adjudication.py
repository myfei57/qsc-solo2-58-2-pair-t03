"""Deterministic adjudication when several rules match the same field."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from maskhub.rule.rule import Rule
from maskhub.rule.specificity import Specificity, measure


def _rank(rule: Rule) -> tuple[int, tuple[int, int, int], str]:
    """Total ordering over rules: the best adjudication candidate sorts first.

    Declared priority dominates; pattern specificity breaks priority ties;
    the identifier is the final deterministic tiebreaker, so the outcome
    never depends on registration order.
    """

    return (-rule.priority, measure(rule.field_pattern).rank(), rule.identifier)


@dataclass(frozen=True)
class Contender:
    """One matched rule and why it won or lost the adjudication."""

    rule: str
    pattern: str
    priority: int
    specificity: Specificity
    outcome: str  # "winner" or "defeated"
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "pattern": self.pattern,
            "priority": self.priority,
            "specificity": self.specificity.as_dict(),
            "outcome": self.outcome,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Decision:
    """The adjudicated outcome for one field, with a full explanation."""

    field: str
    rule: str | None
    action: str | None
    contenders: tuple[Contender, ...]
    explanation: str

    @property
    def matched(self) -> bool:
        return self.rule is not None

    @property
    def contested(self) -> bool:
        return len(self.contenders) > 1

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "rule": self.rule,
            "action": self.action,
            "matched": self.matched,
            "contested": self.contested,
            "explanation": self.explanation,
            "contenders": [item.as_dict() for item in self.contenders],
        }


def adjudicate(field_name: str, rules: Iterable[Rule]) -> Decision:
    """Pick the single rule that governs a field, explaining every loser."""

    matched = sorted((rule for rule in rules if rule.matches(field_name)), key=_rank)
    if not matched:
        return Decision(
            field=field_name,
            rule=None,
            action=None,
            contenders=(),
            explanation=f"no rule pattern matches field {field_name!r}",
        )
    winner = matched[0]
    losers = matched[1:]
    contenders = [
        Contender(
            rule=winner.identifier,
            pattern=winner.field_pattern,
            priority=winner.priority,
            specificity=measure(winner.field_pattern),
            outcome="winner",
            reason=_winner_reason(winner, losers),
        )
    ]
    contenders.extend(
        Contender(
            rule=loser.identifier,
            pattern=loser.field_pattern,
            priority=loser.priority,
            specificity=measure(loser.field_pattern),
            outcome="defeated",
            reason=f"defeated by {winner.identifier!r}: {_decisive(winner, loser)}",
        )
        for loser in losers
    )
    return Decision(
        field=field_name,
        rule=winner.identifier,
        action=winner.action,
        contenders=tuple(contenders),
        explanation=_explanation(field_name, winner, losers),
    )


def adjudicate_all(field_names: Iterable[str], rules: Iterable[Rule]) -> list[Decision]:
    materialized = list(rules)
    return [adjudicate(name, materialized) for name in field_names]


def _winner_reason(winner: Rule, losers: list[Rule]) -> str:
    if not losers:
        return "only matching rule"
    return (
        f"won against {len(losers)} other matching rule(s): "
        f"{_decisive(winner, losers[0])}"
    )


def _explanation(field_name: str, winner: Rule, losers: list[Rule]) -> str:
    if not losers:
        return f"field {field_name!r} matched only rule {winner.identifier!r}"
    return (
        f"field {field_name!r} matched {len(losers) + 1} rules; "
        f"{winner.identifier!r} selected by {_decisive(winner, losers[0])}"
    )


def _decisive(winner: Rule, loser: Rule) -> str:
    """Describe the first adjudication criterion that separates the two."""

    if winner.priority != loser.priority:
        return f"higher priority ({winner.priority} > {loser.priority})"
    winning = measure(winner.field_pattern)
    losing = measure(loser.field_pattern)
    if winning.exact != losing.exact:
        return "exact pattern beats wildcard pattern"
    if winning.literals != losing.literals:
        return f"more literal characters ({winning.literals} > {losing.literals})"
    if winning.wildcards != losing.wildcards:
        return f"fewer wildcards ({winning.wildcards} < {losing.wildcards})"
    return f"identifier {winner.identifier!r} sorts before {loser.identifier!r}"
