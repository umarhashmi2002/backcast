"""Property-based tests (hypothesis) for Backcast's pure invariants.

These assert the *laws* the system relies on — HMAC soundness, the L2/cosine
ranking equivalence, monotonic counterfactual scoring, and hash-chain tamper
detection — over a wide range of generated inputs, with no DB or AWS.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from backcast.api.ingest import _severity
from backcast.api.security import sign_payload, verify_webhook
from backcast.memory.ledger import compute_entry_hash
from backcast.memory.models import Severity
from backcast.memory.scoring import cosine_from_l2, cosine_similarity
from backcast.simulation.model import DeterministicIncidentModel, score_outcome
from backcast.simulation.scenarios import SCENARIOS

# --------------------------------------------------------------------------- #
# 1. HMAC webhook authentication is sound and tamper-sensitive
# --------------------------------------------------------------------------- #

_secrets = st.text(min_size=1, max_size=40)
_bodies = st.binary(min_size=0, max_size=256)
_timestamps = st.integers(min_value=0, max_value=2_000_000_000)


@given(secret=_secrets, body=_bodies, ts=_timestamps)
def test_valid_signature_always_verifies(secret: str, body: bytes, ts: int) -> None:
    sig = sign_payload(secret, body, ts)
    # Verified at the exact same instant → always within max_age.
    assert (
        verify_webhook(secret=secret, body=body, signature=sig, timestamp=str(ts), now=ts) is True
    )


@given(
    secret=_secrets, body=_bodies, ts=_timestamps, skew=st.integers(min_value=301, max_value=10_000)
)
def test_stale_timestamp_is_rejected(secret: str, body: bytes, ts: int, skew: int) -> None:
    sig = sign_payload(secret, body, ts)
    assert (
        verify_webhook(secret=secret, body=body, signature=sig, timestamp=str(ts), now=ts + skew)
        is False
    )


@given(secret=_secrets, body=_bodies, ts=_timestamps, other=_bodies)
def test_body_tampering_is_detected(secret: str, body: bytes, ts: int, other: bytes) -> None:
    assume(other != body)
    sig = sign_payload(secret, body, ts)
    assert (
        verify_webhook(secret=secret, body=other, signature=sig, timestamp=str(ts), now=ts) is False
    )


@given(secret=_secrets, other=_secrets, body=_bodies, ts=_timestamps)
def test_wrong_secret_is_rejected(secret: str, other: str, body: bytes, ts: int) -> None:
    assume(other != secret)
    sig = sign_payload(secret, body, ts)
    assert (
        verify_webhook(secret=other, body=body, signature=sig, timestamp=str(ts), now=ts) is False
    )


# --------------------------------------------------------------------------- #
# 2. L2 distance ranks candidates identically to cosine (for unit vectors)
# --------------------------------------------------------------------------- #

_component = st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False)


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec]


def _l2(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


@given(distances=st.lists(st.floats(min_value=0.0, max_value=2.0), min_size=2, max_size=20))
def test_cosine_from_l2_is_antitone(distances: list[float]) -> None:
    """Smaller L2 distance never yields smaller cosine — so the two orderings agree."""
    for d1, d2 in pairwise(sorted(distances)):
        assert cosine_from_l2(d1) >= cosine_from_l2(d2) - 1e-9


@given(
    raw_q=st.lists(_component, min_size=3, max_size=8),
    raw_cands=st.lists(st.lists(_component, min_size=3, max_size=8), min_size=2, max_size=8),
)
@settings(max_examples=150)
def test_l2_ranking_equals_cosine_ranking(raw_q: list[float], raw_cands: list[float]) -> None:
    """Ordering candidates by ascending L2 yields non-increasing cosine similarity."""
    assume(math.sqrt(sum(x * x for x in raw_q)) > 1e-6)
    cands = [
        c for c in raw_cands if len(c) == len(raw_q) and math.sqrt(sum(x * x for x in c)) > 1e-6
    ]
    assume(len(cands) >= 2)
    q = _unit(raw_q)
    unit_cands = [_unit(c) for c in cands]
    by_l2 = sorted(unit_cands, key=lambda c: _l2(q, c))
    cosines = [cosine_similarity(q, c) for c in by_l2]
    for hi, lo in pairwise(cosines):
        assert hi >= lo - 1e-6


# --------------------------------------------------------------------------- #
# 3. Counterfactual scoring is bounded and monotonic in every penalty
# --------------------------------------------------------------------------- #

_risk = st.floats(min_value=0.0, max_value=1.0)
_cost = st.floats(min_value=0.0, max_value=10.0)
_time = st.floats(min_value=0.0, max_value=1200.0)
_unnec = st.integers(min_value=0, max_value=10)


@given(recurred=st.booleans(), t=_time, u=_unnec, risk=_risk, cost=_cost)
def test_score_upper_bound_and_no_leak(
    recurred: bool, t: float, u: int, risk: float, cost: float
) -> None:
    recovered_score = score_outcome(
        recovered=True,
        recurred=recurred,
        time_to_recovery_s=t,
        unnecessary_actions=u,
        risk=risk,
        cost=cost,
    )
    failed_score = score_outcome(
        recovered=False,
        recurred=recurred,
        time_to_recovery_s=t,
        unnecessary_actions=u,
        risk=risk,
        cost=cost,
    )
    assert recovered_score <= 1.0  # base 1.0 minus non-negative penalties
    assert failed_score <= 0.0  # a non-recovered branch can never score positive
    assert recovered_score >= failed_score  # recovering is never worse, all else equal


@given(
    recovered=st.booleans(),
    recurred=st.booleans(),
    t=_time,
    risk=_risk,
    cost=_cost,
    u1=_unnec,
    u2=_unnec,
)
def test_more_unnecessary_actions_never_helps(
    recovered: bool, recurred: bool, t: float, risk: float, cost: float, u1: int, u2: int
) -> None:
    assume(u1 <= u2)
    lo = score_outcome(
        recovered=recovered,
        recurred=recurred,
        time_to_recovery_s=t,
        unnecessary_actions=u1,
        risk=risk,
        cost=cost,
    )
    hi = score_outcome(
        recovered=recovered,
        recurred=recurred,
        time_to_recovery_s=t,
        unnecessary_actions=u2,
        risk=risk,
        cost=cost,
    )
    assert lo >= hi  # more wasted actions → lower (or equal) score


@given(key=st.sampled_from(sorted(SCENARIOS)))
def test_permanent_fix_beats_temporary_relief(key: str) -> None:
    """A remediation that fixes the true cause outscores one that only relieves it."""
    scenario = SCENARIOS[key]
    model = DeterministicIncidentModel()
    fixers = [n for n, e in scenario.remediations.items() if e.fixes]
    relievers = [n for n, e in scenario.remediations.items() if e.relieves and not e.fixes]
    assume(fixers and relievers)
    best_fix = max(model.simulate(scenario, [n]).score for n in fixers)
    best_relief = max(model.simulate(scenario, [n]).score for n in relievers)
    assert best_fix > best_relief


# --------------------------------------------------------------------------- #
# 4. The event ledger's hash chain detects any tampering or reordering
# --------------------------------------------------------------------------- #

_payload = st.dictionaries(
    keys=st.text(min_size=1, max_size=8),
    values=st.one_of(st.text(max_size=16), st.integers(), st.booleans()),
    max_size=5,
)
_entry = st.tuples(
    st.text(min_size=1, max_size=16), _payload, st.one_of(st.none(), st.text(max_size=12))
)


def _build_chain(entries: list[tuple[str, dict[str, Any], str | None]]) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    prev: str | None = None
    for seq, (etype, payload, actor) in enumerate(entries, start=1):
        entry_hash = compute_entry_hash(prev, seq, etype, payload, actor)
        chain.append(
            {
                "seq": seq,
                "event_type": etype,
                "payload": payload,
                "actor": actor,
                "prev_hash": prev,
                "entry_hash": entry_hash,
            }
        )
        prev = entry_hash
    return chain


def _verify(chain: list[dict[str, Any]]) -> bool:
    prev: str | None = None
    for row in chain:
        expected = compute_entry_hash(
            prev, row["seq"], row["event_type"], row["payload"], row["actor"]
        )
        if expected != row["entry_hash"] or row["prev_hash"] != prev:
            return False
        prev = row["entry_hash"]
    return True


@given(entries=st.lists(_entry, min_size=1, max_size=12))
def test_wellformed_chain_verifies(entries: list[tuple[str, dict[str, Any], str | None]]) -> None:
    assert _verify(_build_chain(entries)) is True


@given(
    entries=st.lists(_entry, min_size=1, max_size=12), idx=st.integers(min_value=0, max_value=11)
)
def test_payload_tampering_breaks_the_chain(
    entries: list[tuple[str, dict[str, Any], str | None]], idx: int
) -> None:
    chain = _build_chain(entries)
    victim = idx % len(chain)
    # Mutate a stored payload without recomputing its (or any later) hash.
    chain[victim]["payload"] = {**chain[victim]["payload"], "__tampered__": True}
    assert _verify(chain) is False


@given(entries=st.lists(_entry, min_size=2, max_size=12))
def test_reordering_breaks_the_chain(entries: list[tuple[str, dict[str, Any], str | None]]) -> None:
    chain = _build_chain(entries)
    chain[0], chain[1] = chain[1], chain[0]  # swap two entries, keep their hashes
    assert _verify(chain) is False


# --------------------------------------------------------------------------- #
# 5. Severity coercion always lands on a valid level
# --------------------------------------------------------------------------- #


@given(value=st.text(max_size=12))
def test_severity_is_always_valid(value: str) -> None:
    result = _severity(value)
    assert isinstance(result, Severity)
    if value in {s.value for s in Severity}:
        assert result.value == value
    elif value == "":
        assert result is Severity.sev3


@given(value=st.one_of(st.none(), st.integers(), st.booleans()))
def test_severity_defaults_to_sev3_for_non_levels(value: object) -> None:
    assert _severity(value) is Severity.sev3
