"""Somo API — M2.

Run:   uvicorn app:app --reload --host 0.0.0.0 --port 8000
Flow:  POST /api/diagnose  ->  GET /api/lesson (stream)  ->  POST /api/check
       wrong -> GET /api/reexplain (stream)   right -> GET /api/next?difficulty=harder
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import config
import llm
import pipeline
import prompts
import sessions

app = FastAPI(title="Somo")
executor = ThreadPoolExecutor(max_workers=8)  # background work: verification, check questions


class CheckQuestion(BaseModel):
    question: str = Field(description="The question, in the student's language")
    expected_answer: str = Field(description="The expected answer only, e.g. 'x = 3'")


class CheckRequest(BaseModel):
    session: str
    answer: str


# ---------- Helpers ----------

def _session(sid: str) -> dict:
    try:
        return sessions.get(sid)
    except KeyError:
        raise HTTPException(404, "Session not found. Snap the problem again.")


def _ctx(s: dict) -> dict:
    """Fields every prompt needs."""
    cur = config.CURRICULA[s["curriculum"]]
    d = s["diagnosis"]
    return {
        "context": cur["context"], "analogies": cur["analogies"], "language": s["language"],
        "problem": d.problem, "concept": d.concept,
    }


def _make_check(s: dict, difficulty: str) -> CheckQuestion:
    q, _ = llm.structured(prompts.CHECK_PROMPT.format(difficulty=difficulty, **_ctx(s)), CheckQuestion)
    s["check"] = q  # expected answer stays on the server
    return q


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream(gen):
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _analogy(lesson: str) -> str:
    """Pull the analogy paragraph out of the lesson, so a re-explanation can use a different one."""
    parts = re.split(r"\*\*[^*]+\*\*", lesson)
    return parts[3].strip()[:300] if len(parts) > 3 else ""


# ---------- Routes ----------

@app.post("/api/diagnose")
async def api_diagnose(
    image: UploadFile = File(...),
    language: str = Form("English"),
    curriculum: str = Form(config.DEFAULT_CURRICULUM),
):
    if language not in config.LANGUAGES:
        raise HTTPException(400, f"language must be one of {config.LANGUAGES}")
    if curriculum not in config.CURRICULA:
        raise HTTPException(400, f"curriculum must be one of {list(config.CURRICULA)}")
    data = await image.read()
    suffix = Path(image.filename or "").suffix.lower()
    mime = image.content_type if (image.content_type or "").startswith("image/") else config.IMAGE_MIME_TYPES.get(suffix)
    if not mime:
        raise HTTPException(400, "Please upload a photo (JPEG or PNG).")
    try:
        d, provider = await run_in_threadpool(pipeline.diagnose, llm.Image(data, mime), curriculum)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Somo couldn't read that photo right now. Please try again. ({str(e)[:120]})")
    sid = sessions.create(diagnosis=d, language=language, curriculum=curriculum, provider=provider)
    # Verification runs in the background while the lesson streams (hides ~4s of latency)
    sessions.get(sid)["verify_future"] = executor.submit(pipeline.verify, d)
    return {"session": sid, "diagnosis": d.model_dump(), "provider": provider}


@app.get("/api/lesson")
def api_lesson(session: str):
    s = _session(session)
    d = s["diagnosis"]
    prompt = prompts.LESSON_PROMPT.format(
        transcription=d.transcription,
        error_step=d.error_step or "(no mistake)",
        error_explanation=d.error_explanation or "(none)",
        **_ctx(s),
    )
    check_future = executor.submit(_make_check, s, "slightly easier")  # ready by the time the lesson ends

    def gen():
        lesson = []
        try:
            for chunk, provider in llm.stream_text(prompt):
                lesson.append(chunk)
                yield _sse("chunk", {"text": chunk, "provider": provider})
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"message": f"The lesson stopped early. Tap to try again. ({str(e)[:100]})"})
            return
        s["lesson"] = "".join(lesson)
        try:
            v = s["verify_future"].result(timeout=30)
        except Exception:  # noqa: BLE001
            v = {"answers_match": False, "confidence": "low", "independent_answer": "", "provider": None}
        s["verification"] = v
        yield _sse("verification", v)
        try:
            yield _sse("check", {"question": check_future.result(timeout=30).question})
        except Exception:  # noqa: BLE001
            yield _sse("error", {"message": "Couldn't make a check question. Tap to try again."})
        yield _sse("done", {})

    return _stream(gen())


@app.post("/api/check")
def api_check(req: CheckRequest):
    s = _session(req.session)
    q = s.get("check")
    if not q:
        raise HTTPException(400, "No check question yet.")
    grade_prompt = prompts.GRADE_PROMPT.format(
        question=q.question, expected=q.expected_answer, answer=req.answer, language=s["language"]
    )
    try:
        reply, provider = llm.text(grade_prompt, config.GEMMA_MODEL)  # Gemma: fast, cheap grading
        verdict, _, feedback = reply.strip().partition("|")
        correct = verdict.strip().upper().startswith("CORRECT")
    except Exception:  # noqa: BLE001 — every model down: fall back to an exact match
        correct = pipeline._normalize(req.answer) == pipeline._normalize(q.expected_answer)
        feedback, provider = "", "local"
    sessions.record_attempt(s, q.question, req.answer, correct)
    s["last_answer"] = req.answer
    return {
        "correct": correct,
        "feedback": feedback.strip(),
        "provider": provider,
        "mastery": s["mastery"],
    }


@app.get("/api/reexplain")
def api_reexplain(session: str):
    s = _session(session)
    q = s.get("check")
    if not q:
        raise HTTPException(400, "No check question yet.")
    prompt = prompts.REEXPLAIN_PROMPT.format(
        question=q.question, answer=s.get("last_answer", ""), expected=q.expected_answer,
        previous_analogy=_analogy(s.get("lesson", "")), **_ctx(s),
    )
    next_future = executor.submit(_make_check, s, "easier")

    def gen():
        try:
            for chunk, provider in llm.stream_text(prompt):
                yield _sse("chunk", {"text": chunk, "provider": provider})
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"message": f"Couldn't explain that right now. Tap to try again. ({str(e)[:100]})"})
            return
        try:
            yield _sse("check", {"question": next_future.result(timeout=30).question})
        except Exception:  # noqa: BLE001
            yield _sse("error", {"message": "Couldn't make a new question. Tap to try again."})
        yield _sse("done", {})

    return _stream(gen())


@app.get("/api/next")
def api_next(session: str, difficulty: str = "harder"):
    """After a correct answer: a harder (or easier) question on the same concept."""
    s = _session(session)
    level = {"harder": "harder", "easier": "easier", "same": "about as hard"}.get(difficulty, "harder")
    try:
        q = _make_check(s, level)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Couldn't make a question right now. ({str(e)[:100]})")
    return {"question": q.question}


@app.get("/api/config")
def api_config():
    return {
        "languages": config.LANGUAGES,
        "curricula": {k: v["label"] for k, v in config.CURRICULA.items()},
        "default_curriculum": config.DEFAULT_CURRICULUM,
    }


# ---------- UI (M3) ----------

if Path("static/index.html").exists():
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
else:
    @app.get("/", response_class=HTMLResponse)
    def home():
        return "<h1>Somo API is running</h1><p>The UI arrives in M3. Try <a href='/docs'>/docs</a>.</p>"
