from enum import Enum


class ConversationState(str, Enum):
    MENU = "MENU"
    SEARCHING = "SEARCHING"
    SEARCH_DISAMBIGUATION = "SEARCH_DISAMBIGUATION"
    BROWSING_CATEGORIES = "BROWSING_CATEGORIES"
    CATEGORY_SELECTED = "CATEGORY_SELECTED"
    VIEWING_RESULTS = "VIEWING_RESULTS"
    SELECTING_PRODUCT = "SELECTING_PRODUCT"
    VIEWING_PRICE = "VIEWING_PRICE"
    RFQ_FLOW = "RFQ_FLOW"
    DIRECT_RFQ = "DIRECT_RFQ"
    TALK_TO_AGENT = "TALK_TO_AGENT"
    IDLE = "IDLE"


STATE_DESCRIPTIONS = {
    ConversationState.MENU.value: "buyer entry point",
    ConversationState.SEARCHING.value: "awaiting product search text",
    ConversationState.SEARCH_DISAMBIGUATION.value: "awaiting product selection after ambiguous search",
    ConversationState.BROWSING_CATEGORIES.value: "awaiting category selection",
    ConversationState.CATEGORY_SELECTED.value: "awaiting product selection within a category",
    ConversationState.VIEWING_RESULTS.value: "showing supplier offers",
    ConversationState.SELECTING_PRODUCT.value: "awaiting quantity for selected offer",
    ConversationState.VIEWING_PRICE.value: "awaiting next action after pricing view",
    ConversationState.RFQ_FLOW.value: "awaiting facility and location for RFQ",
    ConversationState.DIRECT_RFQ.value: "awaiting direct RFQ pipe-format input",
    ConversationState.TALK_TO_AGENT.value: "awaiting sales handoff details",
    ConversationState.IDLE.value: "no active conversation",
}


def is_valid_state(value: str | None) -> bool:
    if not value:
        return False
    return value in STATE_DESCRIPTIONS
