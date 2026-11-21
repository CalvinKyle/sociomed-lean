from pathlib import Path

import pytest

from app.core.conversation_copy import conversation_message, load_conversation_copy


def test_conversation_copy_is_editable_and_contains_end_flow():
    copy = load_conversation_copy()

    assert len(copy) >= 50
    assert "END" in copy["main_menu"]
    assert "session is now closed" in copy["conversation_closed"]
    assert "SocioMed" not in "\n".join(copy.values())


def test_conversation_copy_requires_documented_placeholders():
    assert "RFQ #42" in conversation_message("direct_rfq_received", rfq_id=42)
    with pytest.raises(KeyError, match="Missing field 'rfq_id'"):
        conversation_message("direct_rfq_received")


def test_human_readable_copy_review_lists_every_copy_key():
    copy = load_conversation_copy()
    review_doc = Path("docs/WHATSAPP_RESPONSE_COPY.md").read_text(encoding="utf-8")

    assert all(f"`{key}`" in review_doc for key in copy)


def test_uploaded_business_wording_is_loaded_verbatim():
    copy = load_conversation_copy()

    assert copy["main_menu"].startswith("Welcome to SocioMED!")
    assert "You may type a product immediately." in copy["main_menu"]
    assert "we shall notify the sales team to follow up" in copy["help"]
    assert "connect you directly with a salesperson" in copy["sales_prompt_short"]
    assert "Need 500 pairs of gloves urgently" in copy["sales_prompt"]
    assert copy["search_no_match"].endswith(
        "Reply SEARCH to try another term, or SALES for help."
    )
