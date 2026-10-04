"""Static check that an active policy covers every declared sensitive field."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from maskhub.catalog.dataset import DatasetRegistry
from maskhub.errors import NotFound
from maskhub.policy.registry import PolicyRegistry
from maskhub.rule.adjudication import adjudicate
from maskhub.rule.registry import RuleRegistry


@dataclass(frozen=True)
class CoverageReport:
    policy: str
    dataset: str
    covered: tuple[str, ...]
    uncovered: tuple[str, ...]
    unmatched_rules: tuple[str, ...]
    selected_rules: dict[str, str]
    snapshot_id: str | None

    @property
    def complete(self) -> bool:
        return not self.uncovered

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["complete"] = self.complete
        return payload


def check_coverage(
    policy_id: str,
    dataset_id: str,
    policies: PolicyRegistry,
    datasets: DatasetRegistry,
    rules: RuleRegistry,
    snapshots=None,
) -> CoverageReport:
    policy = policies.get(policy_id)
    if not policy.covers(dataset_id):
        raise NotFound(f"policy {policy_id} does not target dataset {dataset_id}")
    dataset = datasets.get(dataset_id)

    policy_rules = _policy_rules(policy, rules, snapshots)
    sensitive = [item.name for item in dataset.masked_fields()]
    covered: list[str] = []
    uncovered: list[str] = []
    matched: set[str] = set()
    selected_rules: dict[str, str] = {}
    for name in sensitive:
        decision = adjudicate(name, policy_rules)
        if decision.selected_rule is None:
            uncovered.append(name)
            continue
        covered.append(name)
        selected_rules[name] = decision.selected_rule
        matched.update(item.rule_id for item in decision.candidates)
    unmatched = tuple(sorted(set(policy.rules) - matched))
    return CoverageReport(
        policy=policy.identifier,
        dataset=dataset.identifier,
        covered=tuple(covered),
        uncovered=tuple(uncovered),
        unmatched_rules=unmatched,
        selected_rules=selected_rules,
        snapshot_id=policy.snapshot_id,
    )


def _policy_rules(policy, rules: RuleRegistry, snapshots):
    if snapshots is not None and policy.snapshot_id:
        snapshot = snapshots.get(policy.snapshot_id)
        return [snapshot.rule(rule_id) for rule_id in policy.rules]
    return [rules.get(rule_id) for rule_id in policy.rules]
