"""Somo smoke test: confirms your Gemini API key works with both models.

Usage:
    python smoke_test.py                 # text-only check
    python smoke_test.py problem.jpg     # also tests reading a photo of a problem
"""
import os
import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

GEMINI_MODEL = "gemini-flash-latest"   # always points to the current Flash model
GEMMA_MODEL = "gemma-4-26b-a4b-it"     # Gemma 4 served through the Gemini API

# 1. Gemini, text
r = client.models.generate_content(
    model=GEMINI_MODEL,
    contents="In one sentence of Swahili, explain what a variable is in algebra.",
)
print(f"[Gemini OK] {r.text.strip()}\n")

# 2. Gemma 4, text
r = client.models.generate_content(
    model=GEMMA_MODEL,
    contents="A student says 2x + 3 = 11 means x = 7. Correct or incorrect? Answer in one word.",
)
print(f"[Gemma 4 OK] {r.text.strip()}\n")

# 3. Optional: Gemini reads a photo of a problem
if len(sys.argv) > 1:
    path = sys.argv[1]
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    with open(path, "rb") as f:
        image = types.Part.from_bytes(data=f.read(), mime_type=mime)
    r = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            image,
            "Transcribe this math problem and any student work. "
            "If there is a mistake, name the exact step where it happens.",
        ],
    )
    print(f"[Gemini vision OK]\n{r.text.strip()}")