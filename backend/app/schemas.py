from datetime import date
from pydantic import BaseModel, EmailStr, Field, ConfigDict

class RegisterIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class ClientIn(BaseModel):
    name: str
    business_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""

class ClientOut(ClientIn):
    id: int
    model_config = ConfigDict(from_attributes=True)

class ItemIn(BaseModel):
    description: str
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)

class InvoiceIn(BaseModel):
    client_id: int | None = None
    number: str
    issue_date: date
    due_date: date
    status: str = "Sent"
    tax_rate: float = Field(default=0, ge=0, le=100)
    discount: float = Field(default=0, ge=0)
    notes: str = ""
    items: list[ItemIn] = []

class PaymentIn(BaseModel):
    amount: float = Field(gt=0)
    paid_at: date = date.today()
    method: str = "Bank transfer"
    note: str = ""

class ExpenseIn(BaseModel):
    name: str
    amount: float = Field(gt=0)
    date: date
    category: str = "Other"
    vendor: str = ""
    payment_method: str = "Card"
    notes: str = ""

class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
