"""A small library of deterministic incident scenarios.

Each scenario has a hidden *true cause* and a set of candidate remediations with
*defined effects*. The LLM may explain or choose remediations, but whether an
action actually resolves the incident is decided here — never invented by the
model. This is what makes counterfactual comparison sound rather than a
hallucinated "what-if".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemediationEffect:
    """The deterministic effect of applying a remediation to an incident."""

    fixes: bool = False  # permanently resolves the true cause
    relieves: bool = False  # temporary relief only; the symptom recurs
    recovery_seconds: float = 60.0  # time spent applying + observing
    risk: float = 0.1  # 0..1, chance/severity of collateral impact
    cost: float = 1.0  # relative operational cost


@dataclass(frozen=True)
class Scenario:
    key: str
    true_cause: str
    description: str
    remediations: dict[str, RemediationEffect]


SCENARIOS: dict[str, Scenario] = {
    "db_pool_exhaustion": Scenario(
        key="db_pool_exhaustion",
        true_cause="a deploy lowered the DB connection pool size, causing exhaustion",
        description="payments-api 5xx; DB connection pool saturated after a deploy",
        remediations={
            "rollback-deploy": RemediationEffect(
                fixes=True, recovery_seconds=120, risk=0.2, cost=1.0
            ),
            "increase-pool": RemediationEffect(
                fixes=True, recovery_seconds=210, risk=0.3, cost=1.3
            ),
            "restart-service": RemediationEffect(
                relieves=True, recovery_seconds=60, risk=0.1, cost=0.5
            ),
            "scale-out": RemediationEffect(recovery_seconds=90, risk=0.2, cost=2.0),
            "wait": RemediationEffect(recovery_seconds=0.0, risk=0.0, cost=0.0),
        },
    ),
    "memory_leak": Scenario(
        key="memory_leak",
        true_cause="a deploy introduced a memory leak that OOM-kills the service",
        description="checkout-service OOMKilled repeatedly after a deploy",
        remediations={
            "rollback-deploy": RemediationEffect(
                fixes=True, recovery_seconds=150, risk=0.2, cost=1.0
            ),
            "increase-memory-limit": RemediationEffect(
                relieves=True, recovery_seconds=90, risk=0.1, cost=0.8
            ),
            "restart-service": RemediationEffect(
                relieves=True, recovery_seconds=60, risk=0.1, cost=0.5
            ),
            "wait": RemediationEffect(recovery_seconds=0.0, risk=0.0, cost=0.0),
        },
    ),
    "cert_expiry": Scenario(
        key="cert_expiry",
        true_cause="the serving TLS certificate expired and was not rotated",
        description="auth-service TLS handshake failures",
        remediations={
            "rotate-cert": RemediationEffect(fixes=True, recovery_seconds=90, risk=0.1, cost=0.6),
            "rollback-deploy": RemediationEffect(recovery_seconds=120, risk=0.2, cost=1.0),
            "restart-service": RemediationEffect(recovery_seconds=60, risk=0.1, cost=0.5),
            "wait": RemediationEffect(recovery_seconds=0.0, risk=0.0, cost=0.0),
        },
    ),
}


def get_scenario(key: str) -> Scenario:
    try:
        return SCENARIOS[key]
    except KeyError as exc:
        raise KeyError(f"unknown scenario '{key}'; known: {sorted(SCENARIOS)}") from exc
