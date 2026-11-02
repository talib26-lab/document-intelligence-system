"""The shape of the data we want the AI to extract from an invoice.

Every field is optional on purpose: if the document does not clearly show a
value, the AI must return null instead of guessing. Invented numbers in
financial data are worse than missing numbers.
"""

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str | None = Field(None, description="What was sold, as written on the document")
    quantity: float | None = Field(None, description="Quantity, only if clearly shown")
    unit_price: float | None = Field(None, description="Price of one unit, only if clearly shown")
    amount: float | None = Field(None, description="Line total, only if clearly shown")


class InvoiceData(BaseModel):
    invoice_number: str | None = Field(None, description="Invoice number exactly as written, keep leading zeros")
    invoice_date: str | None = Field(None, description="Issue date as YYYY-MM-DD, only if clearly shown")
    due_date: str | None = Field(None, description="Payment due date as YYYY-MM-DD, only if clearly shown")
    supplier_name: str | None = Field(None, description="Company that issued the invoice")
    customer_name: str | None = Field(None, description="Company or person being billed")
    currency: str | None = Field(None, description="3-letter currency code such as USD or BDT")
    subtotal: float | None = Field(None, description="Total before tax, only if clearly shown")
    tax: float | None = Field(None, description="Total tax amount, only if clearly shown")
    total: float | None = Field(None, description="Final amount to pay, only if clearly shown")
    line_items: list[LineItem] = Field(default_factory=list, description="Rows of items; empty list if none are visible")
    uncertain_fields: list[str] = Field(
        default_factory=list,
        description="Names of fields you are not sure about (blurry, ambiguous, or guessed)",
    )