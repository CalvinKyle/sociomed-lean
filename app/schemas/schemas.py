from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CatalogOffer(BaseModel):
    product_id: str
    product_name: str
    brand: str
    sku: Optional[str] = None
    uom: Optional[str] = None
    offer_type: Literal["own_stock", "verified_partner_stock"]
    availability_label: str
    min_qty: int = 1
    starting_price: Optional[int] = None
    max_price: Optional[int] = None
    stock_qty: int = 0
    lead_time_days: Optional[int] = None
    currency: str = "UGX"


class CatalogSearchResponse(BaseModel):
    query: str
    total_matches: int
    matches: List[CatalogOffer]


class CatalogCategoriesResponse(BaseModel):
    total_categories: int
    categories: List[str]


class FeaturedCatalogResponse(BaseModel):
    generated_for: str = "procurement"
    total_featured: int
    featured: List[CatalogOffer]


class BuyerLeadCreate(BaseModel):
    buyer_name: str = Field(min_length=2, max_length=120)
    organization: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=32)
    email: Optional[str] = Field(default=None, max_length=160)
    role: Optional[str] = Field(default=None, max_length=80)
    country: Optional[str] = Field(default=None, max_length=80)
    use_case: Optional[str] = Field(default=None, max_length=1000)
    source: str = Field(default="api", max_length=50)


class BuyerLeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    lead_id: int
    status: str
    buyer_name: str
    organization: str
    created_at: datetime


class RFQLineItemCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    inventory_id: Optional[str] = Field(default=None, max_length=120)
    product_id: Optional[str] = Field(default=None, max_length=120)
    product_name: str = Field(min_length=1, max_length=160)
    brand: Optional[str] = Field(default=None, max_length=160)
    sku: Optional[str] = Field(default=None, max_length=120)
    item_type: Literal["consumable", "equipment", "generic"] = "generic"
    vendor_id: Optional[str] = Field(default=None, max_length=120)
    vendor_name: Optional[str] = Field(default=None, max_length=160)
    is_own_inventory: bool = False
    quantity: int = Field(gt=0)
    uom: Optional[str] = Field(default=None, max_length=80)
    unit_price: Optional[int] = Field(default=None, gt=0)
    currency: Optional[str] = Field(default=None, max_length=10)
    price_source: Optional[str] = Field(default=None, max_length=160)
    stock_verification_status: Literal[
        "verified_in_stock",
        "verified_short_lead_time",
        "partner_confirmation_required",
        "out_of_stock",
        "insufficient_stock",
        "unknown",
        "stale",
    ] = "unknown"


class RFQCreate(BaseModel):
    buyer_name: str = Field(min_length=2, max_length=120)
    organization: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=32)
    email: Optional[str] = Field(default=None, max_length=160)
    delivery_location: str = Field(min_length=2, max_length=200)
    procurement_stage: Literal[
        "budgeting",
        "approval_stage",
        "ready_to_purchase",
        "tender",
        "market_sourcing",
    ] = "market_sourcing"
    required_delivery_date: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    currency: str = Field(default="UGX", max_length=10)
    source: str = Field(default="api", max_length=50)

    product_name: Optional[str] = Field(default=None, max_length=160)
    product_id: Optional[str] = Field(default=None, max_length=120)
    vendor_id: Optional[str] = Field(default=None, max_length=120)
    vendor_name: Optional[str] = Field(default=None, max_length=160)
    vendor_phone: Optional[str] = Field(default=None, max_length=32)
    quantity: Optional[int] = Field(default=None, gt=0)
    items: Optional[list[RFQLineItemCreate]] = Field(default=None, min_length=1)
    request_formal_pfi: bool = False
    manual_review_required: bool = False
    manual_review_reason: Optional[str] = Field(default=None, max_length=300)
    requires_credit: bool = False
    technical_review_required: bool = False
    special_fulfilment_required: bool = False

    @model_validator(mode="after")
    def validate_item_source(self):
        if not self.items and (not self.product_name or not self.quantity):
            raise ValueError("Either `items` or `product_name` + `quantity` must be provided.")
        return self

    def resolved_items(self) -> list[RFQLineItemCreate]:
        if self.items:
            return self.items
        assert self.product_name is not None
        assert self.quantity is not None
        return [
            RFQLineItemCreate(
                product_id=self.product_id,
                product_name=self.product_name,
                vendor_id=self.vendor_id,
                vendor_name=self.vendor_name,
                quantity=self.quantity,
                currency=self.currency,
            )
        ]


class RFQLineItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    inventory_id: Optional[str]
    product_id: Optional[str]
    product_name: str
    brand: Optional[str]
    sku: Optional[str]
    item_type: str
    quantity: int
    uom: Optional[str]
    unit_price: Optional[int]
    line_total: Optional[int]
    currency: str
    stock_verification_status: str


class RFQResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rfq_id: int
    status: str
    supplier_notified: bool
    notification_status: Optional[str] = None
    notification_failure_reason: Optional[str] = None
    created_at: datetime


class RFQStatusUpdate(BaseModel):
    status: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z][A-Za-z0-9_ -]*$")
    order_value: Optional[int] = Field(
        default=None,
        gt=0,
        description=(
            "Final agreed order value (price x quantity). Set when confirming or fulfilling "
            "to enable commission tracking."
        ),
    )
    payment_confirmation_reference: Optional[str] = Field(default=None, min_length=2, max_length=160)

    @model_validator(mode="after")
    def require_payment_reference_for_confirmation(self):
        normalized_status = self.status.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized_status == "confirmed" and not self.payment_confirmation_reference:
            raise ValueError("payment_confirmation_reference is required when confirming an RFQ")
        return self


class RFQStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rfq_id: int
    status: str
