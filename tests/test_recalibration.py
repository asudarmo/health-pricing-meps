"""Tests for the recalibration rule on constructed evidence (M5, issue #47)."""

import dataclasses

import pytest

from health_pricing.models import recalibration as rule


def evidence(**changes):
    base = dict(
        a_e=1.145,
        a_e_lower=1.075,
        a_e_upper=1.220,
        claimants=8000,
        severity_cv2=6.0,
        frequency_p=0.60,
        severity_p=0.30,
        levels_beyond_noise=1,
        levels_compared=13,
        off_book_levels=2,
        off_book_checked=34,
        max_psi=0.004,
        gini_later=0.47,
        gini_earlier=0.39,
    )
    base.update(changes)
    return rule.Evidence(**base)


def test_no_gap_and_stable_evidence_does_nothing():
    result = rule.recommend(evidence(a_e=1.02, a_e_lower=0.95, a_e_upper=1.09))
    assert result.action == rule.DO_NOTHING and result.base_rate_factor == 1.0
    assert not result.checks["gap"]


def test_a_gap_with_stable_relativities_and_mix_is_a_rebase_weighted_by_credibility():
    small = rule.recommend(evidence(claimants=1500))
    assert small.action == rule.REBASE
    assert 0 < small.credibility < 1
    assert small.base_rate_factor == pytest.approx(1 + small.credibility * 0.145)
    assert small.base_rate_factor < 1.145
    full = rule.recommend(evidence(claimants=10**6))
    assert full.credibility == 1.0 and full.base_rate_factor == pytest.approx(1.145)
    assert 1.0 < full.lower_base_rate_factor < full.base_rate_factor
    assert full.persistence_credibility == pytest.approx(
        rule.persistence_credibility(evidence(claimants=10**6))
    )


def test_persistence_credibility_falls_as_the_interval_widens():
    narrow = rule.persistence_credibility(evidence(a_e_lower=1.13, a_e_upper=1.16))
    wide = rule.persistence_credibility(evidence())
    assert 0 < wide < narrow < 1


def test_a_gap_below_one_is_also_a_rebase_downwards():
    result = rule.recommend(evidence(a_e=0.85, a_e_lower=0.80, a_e_upper=0.91))
    assert result.action == rule.REBASE and result.base_rate_factor < 1.0


def test_a_joint_change_in_the_relativities_is_a_refit_when_the_ranking_holds():
    result = rule.recommend(evidence(severity_p=0.01))
    assert result.action == rule.REFIT and result.base_rate_factor == 1.0


def test_many_levels_beyond_noise_is_a_structure_change_by_the_chance_count():
    assert rule.chance_probability(5, 13) < rule.ALPHA
    assert rule.recommend(evidence(levels_beyond_noise=5)).action == rule.REFIT
    assert rule.recommend(evidence(off_book_levels=6)).action == rule.REFIT


def test_a_structure_change_with_a_lost_ranking_is_a_review():
    result = rule.recommend(evidence(frequency_p=0.001, gini_later=0.30))
    assert result.action == rule.REVIEW
    assert result.checks["ranking_lost"]


def test_a_structure_change_without_a_gap_is_still_a_refit():
    result = rule.recommend(evidence(a_e=1.01, a_e_lower=0.95, a_e_upper=1.08, severity_p=0.02))
    assert result.action == rule.REFIT


def test_mix_drift_is_reported_but_does_not_change_a_rebase():
    result = rule.recommend(evidence(max_psi=0.2))
    assert result.checks["mix_moved"] and result.action == rule.REBASE
    assert any("mix moved" in line for line in result.reasons)


def test_credibility_follows_the_limited_fluctuation_standard():
    assert rule.full_credibility_claims(0.0) == pytest.approx(1082.4, abs=0.5)
    assert rule.credibility(1082, 0.0) == pytest.approx(1.0, abs=0.01)
    assert rule.credibility(271, 0.0) == pytest.approx(0.5, abs=0.01)


def test_the_chance_probability_of_no_differences_is_one():
    assert rule.chance_probability(0, 13) == 1.0
    assert dataclasses.is_dataclass(evidence())
