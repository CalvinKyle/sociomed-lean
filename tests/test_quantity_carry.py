import pytest
from app.services import whatsapp_service as ws
from app.core.states import ConversationState

@pytest.mark.parametrize('qty,price', [(9,100), (10,90), (49,90), (50,80)])
def test_tier_boundaries(qty, price):
    tiers = [{'min_qty': lo, 'max_qty': hi, 'unit_price': amount, 'price_status': 'verified'} for lo, hi, amount in [(1,9,100),(10,49,90),(50,None,80)]]
    assert ws.price_for_quantity({'pricing': tiers}, qty) == price
    tiers[0]['price_status'] = 'unverified'
    assert ws.price_for_quantity({'pricing': tiers}, qty) is None


def test_quantity_survives_all_browse_transitions(monkeypatch):
    session = {'pending_quantity': 20, 'pending_uom': 'boxes'}
    monkeypatch.setattr(ws, 'get_session', lambda sender: dict(session))
    monkeypatch.setattr(ws, 'save_session', lambda sender, data: (session.clear(), session.update(data)))
    for state in [ConversationState.SEARCH_DISAMBIGUATION, ConversationState.CATEGORY_SELECTED, ConversationState.FAMILY_SELECTED, ConversationState.VIEWING_RESULTS, ConversationState.SELECTING_PRODUCT]:
        ws._transition_session('test', 'SEARCHING', state)
        assert session['pending_quantity'] == 20 and session['pending_uom'] == 'boxes'
    ws._transition_session('test', 'SELECTING_PRODUCT', ConversationState.IDLE)
    assert 'pending_quantity' not in session
