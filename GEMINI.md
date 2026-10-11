# Somo — agent instructions

Somo is a hackathon project (MLH AI Engineer NY Hackathon, today). A student photographs a problem they're stuck on; Somo diagnoses the exact mistake, teaches the concept in the student's home language with English key terms, checks understanding with one question, and loops to a simpler explanation if they get it wrong.

Primary goal: ONE polished, reliable demo loop running live on a phone browser. Prefer simple and working over clever and fragile.

## Stack (do not change without asking)

- Backend: Python 3, FastAPI, uvicorn. SDK: `google-genai` (`from google import genai`). NOT the old `google-generativeai` package.
- Frontend: a single `static/index.html` with vanilla JS and Tailwind via CDN. Mobile-first (designed for ~390px wide). No build step, no React.
- State: in-memory Python dict keyed by a session id. No database.
- Config: API key in `.env` as `GEMINI_API_KEY`, loaded with python-dotenv. Never hardcode or print the key. Never commit `.env`.

## Models (keep in `config.py`)

- `GEMINI_MODEL = "gemini-flash-latest"` — reading images, diagnosing, verifying, teaching.
- `GEMMA_MODEL = "gemma-4-26b-a4b-it"` — grading the check question (fast, cheap). This is our "lightweight / offline-ready" story for the Gemma prize.

## File layout

```
app.py            FastAPI app + routes, serves static/
config.py         model names, supported languages and curricula
pipeline.py       all model calls: diagnose, verify, lesson, grade, reexplain
prompts.py        all prompt templates (keep prompts out of pipeline logic)
sessions.py       in-memory session store + per-concept mastery
static/index.html the whole UI
samples/          test photos of handwritten problems (some with deliberate mistakes)
smoke_test.py     existing API check — leave as is
```

## Pipeline

1. **Diagnose** — `POST /api/diagnose` (multipart: image, language, curriculum) → Gemini with the image, structured JSON output (use `response_mime_type="application/json"` + a Pydantic `response_schema`):
   `{transcription, subject, concept, has_student_work, error_step, error_explanation, final_answer}`
   `error_step` is null if there's no student work or no mistake.
2. **Verify** — a second, independent Gemini call solves the transcribed problem WITHOUT seeing the diagnosis. Compare final answers. If they disagree, mark `confidence: "low"` and the UI says "Let's double-check this one together" instead of asserting an error. Never teach an answer that failed verification as if it were certain.
3. **Teach** — `GET /api/lesson?session=…` streams (Server-Sent Events or chunked text) a short lesson in the chosen language:
   - what the concept is, in plain words
   - where the student went wrong (if `error_step`)
   - one everyday analogy matched to the curriculum region (Tanzania/NECTA → daladala fares, market prices; US/Common Core → subway swipes, bodega prices)
   - one worked example with DIFFERENT numbers than the student's problem
   - a "Key terms" list: home-language term → English term
   Then generate one check question + its expected answer. Store the expected answer server-side only; send only the question to the client.
4. **Check** — `POST /api/check` (session, student_answer) → Gemma grades against the expected answer → `{correct: bool, feedback}` (feedback in the chosen language, one sentence). Update mastery for the concept.
5. **Re-explain** — if incorrect: `GET /api/reexplain?session=…` streams a simpler explanation with a NEW analogy, then a new, easier check question. If correct: show "Level up" and offer a harder question.

Languages: English, Swahili, Spanish at minimum (list in `config.py`, easy to add more). Curricula: "Tanzania (NECTA)" and "US (Common Core)".

## UI (single screen, top to bottom)

- Header "Somo" + language dropdown + curriculum dropdown
- Big "Snap a problem" button (`<input type="file" accept="image/*" capture="environment">`) + image preview
- Diagnosis card: transcription, concept, and the wrong step highlighted
- Lesson card: streams in as it generates; key terms shown as bilingual chips
- Check card: question, answer input, submit → green "Level up" or amber "Let's try it another way" → re-explain
- Clear loading states for every model call. Friendly error message if a call fails, with a retry button.

## Build order — finish and run each milestone before starting the next

1. **M1 Diagnose + verify** — `pipeline.py` functions runnable from a tiny CLI on `samples/` images. Print the JSON. Commit.
2. **M2 API** — FastAPI routes for diagnose, lesson (streaming), check, reexplain. Test with curl. Commit.
3. **M3 UI** — `static/index.html` with the full loop working on a phone browser on the same wifi (`uvicorn app:app --host 0.0.0.0`). Commit.
4. **M4 Loop polish** — re-explain flow, language + curriculum toggles change the lesson, bilingual key terms. Commit.
5. **M5 Real exam practice (Nimble)** — after a correct answer, "Practice like the real exam": use Nimble (`pip install nimble_python`, `NIMBLE_API_KEY` in `.env`) to search the live web for real past exam questions on the diagnosed concept, restricted to the student's curriculum (Tanzania → NECTA past papers; US → NY Regents / state released test items). Extract the page, have Gemini pick ONE question matched to the student's level and return it as structured JSON, and show it in the UI with a source link. Put this in `practice.py`. Cache results per concept so the demo doesn't wait on the web twice. If Nimble fails or finds nothing, fall back to a Gemini-generated question and say so.
6. **M6 Sentry (15 min)** — add the Sentry SDK to FastAPI with tracing so every Gemini, Gemma and Nimble call shows up as a span. `SENTRY_DSN` in `.env`.
7. **M7 Should-haves** — adaptive harder/easier follow-up; simple mastery list per session.
8. **M8 Stretch (only if everything above is solid)** — concept mastery map, voice output, a Gemma-only "offline mode" toggle.

Hard deadline: projects are due at 5 PM. Stop adding features at 3:45 PM.

## Rules for the agent

- Work in small steps. After each step, run it and show the output before moving on.
- Commit after every milestone with a clear message.
- Keep every prompt in `prompts.py`. Ask before changing the stack or adding dependencies.
- Use the photos in `samples/` for testing; don't invent fake image data.
- Don't add auth, databases, Docker, or deployment until asked.
- If a model call fails or returns invalid JSON, retry once, then return a clean error to the UI.