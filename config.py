"""Somo configuration: models, languages, curricula."""

# Gemini: reading images, diagnosing, verifying, teaching
GEMINI_MODEL = "gemini-flash-latest"

# Claude: automatic failover when Gemini is overloaded or too slow
CLAUDE_MODEL = "claude-sonnet-5-5"

# Time budgets (seconds). Gemini gets one quick retry, then Claude takes over.
GEMINI_TIMEOUT_S = 15
CLAUDE_TIMEOUT_S = 40

# Circuit breaker: after Gemini fails, skip it for this long and go straight to Claude
GEMINI_COOLDOWN_S = 60

# Gemma 4 (served through the Gemini API): fast, cheap checks and grading
GEMMA_MODEL = "gemma-4-26b-a4b-it"

LANGUAGES = ["English", "Swahili", "Spanish"]

CURRICULA = {
    "tanzania": {
        "label": "Tanzania (NECTA)",
        "context": "Tanzanian secondary school (Form 1-4), NECTA national exams",
        "analogies": "daladala fares, market prices in shillings, bodaboda rides",
    },
    "us": {
        "label": "US (Common Core)",
        "context": "US public school, Common Core / state standards (e.g. NY Regents)",
        "analogies": "subway swipes, bodega prices in dollars, sports scores",
    },
}

DEFAULT_CURRICULUM = "tanzania"

# Image types Gemini accepts; iPhone photos are often HEIC
IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
}