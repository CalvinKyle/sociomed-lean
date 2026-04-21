from pydantic import BaseModel, ConfigDict

class PFIRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)   # replaces orm_mode = True
    
    request_id: int
    user_id: int
    product_id: int
    quantity: int
    status: str
    created_at: str
    updated_at: str
