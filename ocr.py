"""
Reads handwritten purchase lists using Gemini's vision API.

Tried first and ruled out on real handwriting: local Qwen3-VL-4B (hallucinated
repeated phrases), EasyOCR (pure noise on cursive), the existing Qwen3.6-35B
endpoint (misread the script entirely). General OCR/VLMs are unreliable on
messy handwriting regardless of model size — the fix here is structured JSON
output + mandatory human review before anything saves, not full automation.

This module never saves anything. Callers must always show the returned
draft to a person for review/correction before it touches the database.
"""
import os
from pydantic import BaseModel
from google import genai
from google.genai import types


class PurchaseItem(BaseModel):
    item_name: str
    quantity: float
    unit: str
    price: float


class PurchaseList(BaseModel):
    items: list[PurchaseItem]


_MODEL = "gemini-3.5-flash"

_PROMPT = """You are reading a handwritten purchase/shopping list from a small
restaurant kitchen. For each line item, extract:
- item_name: the name of the item purchased (e.g. "Tomatoes", "Rice", "Oil")
- quantity: the numeric quantity purchased
- unit: the unit for that quantity (e.g. kg, g, liter, ml, pieces, packets, boxes) — infer a reasonable unit if none is written
- price: the PRICE IN RUPEES for that line item. The right-most or last number on
  each line is almost always the price, NOT a weight or quantity. Do not confuse
  price with quantity/weight — this is a common and important mistake to avoid.

Return every line item you can read. If a value is illegible, make your best
reasonable guess rather than omitting the item — the output will be reviewed
and corrected by a person before anything is saved."""


def extract_purchase_items(image_bytes: bytes, mime_type: str = "image/jpeg") -> list[dict]:
    """Send a photo of a handwritten purchase list to Gemini and return a
    list of {item_name, quantity, unit, price} dicts."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=_MODEL,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            _PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PurchaseList,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, PurchaseList):
        raise ValueError("Gemini did not return a parseable structured response")
    return [item.model_dump() for item in parsed.items]
