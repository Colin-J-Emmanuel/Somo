"""Somo configuration: models, languages, curricula."""

# Gemini: reading images, diagnosing, verifying, teaching
GEMINI_MODEL = "gemini-flash-latest"

# Claude: automatic failover when Gemini is overloaded or too slow
CLAUDE_MODEL = "claude-sonnet-5-5"

# Time budgets (seconds). Gemini gets one quick retry, then Claude takes over.
GEMINI_TIMEOUT_S = 15
CLAUDE_TIMEOUT_S = 40
STREAM_TIMEOUT_S = 60   # a full streamed lesson

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
        "exam_label": "NECTA national exams (CSEE Form Four / FTNA Form Two, Basic Mathematics)",
        "exam_query": "NECTA CSEE Basic Mathematics past paper {concept}",
        "exam_domains": ["necta.go.tz", "maktaba.tetea.org"],  # official papers first; open web if empty
    },
    "us": {
        "label": "US (Common Core)",
        "context": "US public school, Common Core / state standards (e.g. NY Regents)",
        "analogies": "subway swipes, bodega prices in dollars, sports scores",
        "exam_label": "New York State Regents exams (Algebra I)",
        "exam_query": "NY Regents Algebra I exam question {concept}",
        "exam_domains": ["jmap.org", "nysedregents.org"],
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

# Nimble (real past exam questions from the live web)
NIMBLE_MAX_RESULTS = 5
NIMBLE_CHARS_PER_PAGE = 20000   # a full past paper has many questions; the one we need may be far down
MIN_PAGE_CHARS = 2000            # shorter than this and the result is a PDF: download and read the PDF itself
PDF_TIMEOUT_S = 12
PDF_MAX_BYTES = 15_000_000
PRACTICE_CACHE_FILE = "practice_cache.json"   # found exam questions, kept across restarts