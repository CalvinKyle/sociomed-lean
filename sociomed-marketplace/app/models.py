from pydantic import BaseModel

class PFIRequest(BaseModel):
    request_id: int
    user_id: int
    product_id: int
    quantity: int
    status: str
    created_at: str
    updated_at: str

    class Config:
        orm_mode = True
