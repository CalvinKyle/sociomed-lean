from app.core.validators import validate_contact_name


def test_validate_contact_name_matches_rfq_contract_limits():
    assert validate_contact_name("Dr. Ali")
    assert not validate_contact_name("")
    assert not validate_contact_name("A")
    assert not validate_contact_name("A" * 121)
    assert not validate_contact_name("+256701234567")
