import asyncio
import pytest
from app.services.rfq_triage import parse_requested_items, resolve_requested_items
from app.services import whatsapp_service as ws

@pytest.mark.parametrize('text,quantities', [('gloves x100, syringes x50, cannulas x20', [100,50,20]), ('100 x gloves; 50 syringes + 20 cannulas', [100,50,20]), ('10 boxes of nitrile gloves', [10]), ('bed and mattress', [1]), ('gauze and bandage', [1])])
def test_item_parser(text, quantities):
    assert [i['quantity'] for i in parse_requested_items(text)] == quantities

def test_compound_and_unmatched():
    assert len(parse_requested_items('stand and bowl', [{'name': 'stand and bowl'}])) == 1
    item = parse_requested_items('unlisted component')[0]
    assert item['quantity_stated'] is False
    assert resolve_requested_items([item], {})[0]['product_name'] == 'unlisted component'
    with pytest.raises(ValueError): parse_requested_items(','.join('item' for _ in range(21)))

@pytest.mark.parametrize('returning', [False, True])
def test_natural_list_confirmation_and_profile(monkeypatch, returning):
    sessions, replies, created = {}, [], []
    profile = {'contact_name': 'Dr Ali', 'organization': 'Test Hospital', 'delivery_location': 'Kampala'} if returning else None
    monkeypatch.setattr(ws, 'get_session', lambda phone: sessions.get(phone))
    monkeypatch.setattr(ws, 'save_session', lambda phone, value: sessions.update({phone: value}))
    monkeypatch.setattr(ws, 'get_cached_data', lambda: {})
    monkeypatch.setattr(ws, '_load_buyer_profile', lambda phone: profile)
    monkeypatch.setattr(ws, 'get_categories', lambda: [])
    async def send(phone, message):
        assert len(message) < 1500
        replies.append(message)
    async def create(**kwargs):
        created.append(kwargs)
        return 1, False
    monkeypatch.setattr(ws, 'send_whatsapp_message', send)
    monkeypatch.setattr(ws, '_create_whatsapp_rfq', create)
    async def run():
        for text in ['gloves x100, syringes x50, cannulas x20'] + ([] if returning else ['Dr Ali', 'Test Hospital', 'Kampala']):
            await ws.handle_incoming_message({'from': '256700000001', 'text': {'body': text}})
        assert not created
        assert 'YES' in replies[-1] and 'x100' in replies[-1]
        await ws.handle_incoming_message({'from': '256700000001', 'text': {'body': 'YES'}})
    asyncio.run(run())
    assert [i['quantity'] for i in created[0]['items']] == [100, 50, 20]
