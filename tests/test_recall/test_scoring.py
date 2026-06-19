from aingram.recall.scoring import (trust_factor, status_factor, mem_type_factor, compose_recall_score)

def test_trust_factor_null_is_neutral():
    assert trust_factor(None) == 0.5
    assert trust_factor(0.9) == 0.9
    assert trust_factor(1.5) == 1.0   # clamp

def test_status_factor_quarantine_ordering():
    assert status_factor('approved') == 1.0
    assert status_factor('pending') == 0.4
    assert status_factor('denied') == 0.0

def test_mem_type_factor_derives_from_kind():
    w = {'semantic': 1.0, 'procedural': 2.0, 'episodic': 0.5}
    assert mem_type_factor('instruction', w) == 2.0   # instruction -> procedural
    assert mem_type_factor('outcome', w) == 0.5       # outcome -> episodic
    assert mem_type_factor(None, w) == 1.0            # unknown -> neutral

def test_compose_multiplies_and_denied_is_zero():
    s = compose_recall_score(1.0, trust_score=0.8, status='approved', kind='fact', type_weights={})
    assert 0 < s <= 1.0
    assert compose_recall_score(1.0, trust_score=1.0, status='denied', kind='fact', type_weights={}) == 0.0
