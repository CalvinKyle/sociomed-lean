from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CatalogOffer(BaseModel):
    product_id: str
    product_name: str
    brand: str
    sku: Optional[str] = None
    uom: Optional[str] = None
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
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


class RFQCreate(BaseModel):
    buyer_name: str = Field(min_length=2, max_length=120)
    organization: str = Field(min_length=2, max_length=160)
    phone: str = Field(min_length=7, max_length=32)
    email: Optional[str] = Field(default=None, max_length=160)
    product_name: str = Field(min_length=2, max_length=160)
    product_id: Optional[str] = Field(default=None, max_length=120)
    vendor_id: Optional[str] = Field(default=None, max_length=120)
    vendor_name: Optional[str] = Field(default=None, max_length=160)
    vendor_phone: Optional[str] = Field(default=None, max_length=32)
    quantity: int = Field(gt=0)
    delivery_location: str = Field(min_length=2, max_length=200)
    notes: Optional[str] = Field(default=None, max_length=2000)
    currency: str = Field(default="UGX", max_length=10)
    source: str = Field(default="api", max_length=50)


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


class RFQStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rfq_id: int
    status: str
