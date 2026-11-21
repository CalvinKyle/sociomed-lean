"""RFQ lifecycle status values.

new       -> RFQ captured, not yet reviewed
quoted    -> price/availability confirmed with buyer
approved  -> owner approved for LPO within rolling cap
lpo_issued -> LPO reference recorded
confirmed -> buyer has committed to proceed
fulfilled -> order completed with the supplier
cancelled -> buyer withdrew or never confirmed
lost      -> buyer proceeded elsewhere
"""

RFQ_STATUSES = ("new", "quoted", "approved", "lpo_issued", "confirmed", "fulfilled", "cancelled", "lost")

BUYER_NOTIFIABLE_STATUSES = {"confirmed", "fulfilled"}


def is_valid_rfq_status(status: str) -> bool:
    return status in RFQ_STATUSES


class InvalidRFQStatus(ValueError):
    """Raised when an RFQ status update is outside the known lifecycle."""
