import pytest
from app.core.uom import buyer_uom, LABELS
from app.models.formatter import format_results

@pytest.mark.parametrize('code', list(LABELS) + ['MYSTERY42', None])
def test_buyer_offer_hides_nulls_and_raw_codes(code):
    reply, options = format_results('Gloves', [{'brand': None, 'uom': code, 'lead_time_days': None, 'pricing': []}])
    assert 'Option 1' in reply
    assert 'Lead time confirmed in quotation' in reply
    for bad in ['None', 'null', 'nan'] + list(LABELS):
        assert bad not in reply
    assert options[0]['uom'] == buyer_uom(code)
