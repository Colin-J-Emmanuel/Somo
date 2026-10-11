"""Somo pipeline — M1: diagnose + verify.

CLI:
    python pipeline.py samples/photo1.jpg          # one photo
    python pipeline.py                             # every photo in samples/
    python pipeline.py samples/photo1.jpg --curriculum us
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from pydantic import BaseModel, Field

import config
import llm
import prompts


# ---------- Schemas (no default values: the Gemini schema doesn't allow them) ----------

class Diagnosis(BaseModel):
    transcription: str = Field(description="The problem, plus the student's work as numbered lines if present")
    problem: str = Field(description="The problem statement only, without student work")
    subject: str
    concept: str = Field(description="Specific concept tested, e.g. 'solving two-step linear equations'")
    has_student_work: bool
    student_answer: str = Field(description="Student's final answer, or empty string")
    error_step: str = Field(description="First wrong line quoted, or empty string if no mistake")
    error_explanation: str = Field(description="What went wrong, or empty string")
    final_answer: str = Field(description="The correct final answer only, e.g. 'x = -2, y = 3' (no working)")
    reading_confidence: str = Field(description="high, medium, or low: how clearly the photo could be read")


class Solution(BaseModel):
    steps: list[str]
    final_answer: str


# ---------- Helpers ----------

def load_image(path: str) -> llm.Image:
    suffix = Path(path).suffix.lower()
    mime = config.IMAGE_MIME_TYPES.get(suffix)
    if not mime:
        raise ValueError(f"Unsupported image type: {suffix}")
    return llm.Image(data=Path(path).read_bytes(), mime=mime)


def _normalize(answer: str) -> str:
    """'B = 4 and T = 16', 'T=16, B=4' -> 'b=4|t=16'; 'x = 4' -> '4'."""
    a = answer.lower().replace("$", "").replace("−", "-")
    parts = [p.replace(" ", "").rstrip(".") for p in re.split(r",|;|\band\b|\n", a) if p.strip()]
    if len(parts) == 1:
        return re.sub(r"^[a-z]=", "", parts[0])   # single answer: drop "x="
    return "|".join(sorted(parts))


def answers_match(problem: str, a: str, b: str) -> bool:
    """Cheap string check first; if it fails, ask Gemma whether they're equivalent."""
    if _normalize(a) == _normalize(b):
        return True
    try:
        reply, _ = llm.text(prompts.EQUIVALENCE_PROMPT.format(problem=problem, a=a, b=b), config.GEMMA_MODEL)
        return reply.strip().upper().startswith("YES")
    except Exception:  # noqa: BLE001 — if every provider is down, be conservative
        return False


# ---------- Pipeline steps ----------

def diagnose(image: llm.Image, curriculum: str = config.DEFAULT_CURRICULUM):
    context = config.CURRICULA[curriculum]["context"]
    return llm.structured(prompts.DIAGNOSE_PROMPT.format(context=context), Diagnosis, image)


def verify(diagnosis: Diagnosis) -> dict:
    """Solve the problem independently (without seeing the diagnosis) and compare answers."""
    solution, provider = llm.structured(prompts.VERIFY_PROMPT.format(problem=diagnosis.problem), Solution)
    match = answers_match(diagnosis.problem, diagnosis.final_answer, solution.final_answer)
    low_reading = diagnosis.reading_confidence.lower() == "low"
    return {
        "independent_answer": solution.final_answer,
        "answers_match": match,
        "confidence": "high" if match and not low_reading else "low",
        "provider": provider,
    }


def run(path: str, curriculum: str = config.DEFAULT_CURRICULUM) -> dict:
    start = time.time()
    d, provider = diagnose(load_image(path), curriculum)
    v = verify(d)
    return {
        "file": path,
        "diagnosis": d.model_dump(),
        "diagnosis_provider": provider,
        "verification": v,
        "seconds": round(time.time() - start, 1),
    }


# ---------- CLI ----------

def main():
    parser = argparse.ArgumentParser(description="Somo M1: diagnose + verify a photo of a math problem")
    parser.add_argument("images", nargs="*", help="Image paths (default: every image in samples/)")
    parser.add_argument("--curriculum", choices=list(config.CURRICULA), default=config.DEFAULT_CURRICULUM)
    args = parser.parse_args()

    samples = Path("samples")
    paths = args.images or sorted(
        str(p) for p in (samples.iterdir() if samples.is_dir() else [])
        if p.suffix.lower() in config.IMAGE_MIME_TYPES
    )
    if not paths:
        sys.exit("No images found. Add photos to samples/ or pass a path.")

    for path in paths:
        try:
            result = run(path, args.curriculum)
        except Exception as e:  # noqa: BLE001
            result = {"file": path, "error": str(e)}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()