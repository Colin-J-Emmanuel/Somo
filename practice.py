"""M5: practice like the real exam.

Nimble searches the live web for real past exam questions on the student's concept,
restricted to their curriculum. Gemini (or Claude, via the router) picks ONE real
question from those pages at the right level. If nothing usable turns up, Somo
writes a question itself and says so.
"""
import io
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, Field

import config
import llm
import observability as obs
import prompts

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font warnings from scanned papers are harmless

_nimble = None
_cache: dict[tuple, "Practice"] = {}


class PickedQuestion(BaseModel):
    question_concept: str = Field(description="The concept the chosen question actually tests, in a few words")
    same_concept: bool = Field(description="True only if question_concept is the same concept the student is learning")
    found: bool = Field(description="True only if a suitable question appears word for word in the sources")
    is_past_exam: bool = Field(description="True only if that source is an official past exam paper (e.g. a NECTA or Regents paper), not a textbook, worksheet or tutoring site")
    question: str = Field(description="The exam question, copied faithfully from the source (translated if asked)")
    expected_answer: str = Field(description="The correct final answer only")
    source_index: int = Field(description="Number of the source the question came from, or -1 if not found")
    exam_name: str = Field(description="Exam and year if the source says, e.g. 'NECTA CSEE 2019'; else empty")


class Practice(BaseModel):
    question: str
    expected_answer: str
    kind: str                  # "past_exam" | "web" (practice question found online) | "generated" (written by Somo)
    real: bool                 # True only for an official past exam paper
    source_url: str
    source_title: str
    exam_name: str
    seconds: float


_STOP = {"a", "an", "the", "of", "by", "and", "using", "with", "to", "in", "for", "solving", "solve"}


def _words(concept: str) -> set[str]:
    return {w.strip(".,()") for w in concept.lower().split()} - _STOP


def _lookup(key: tuple):
    """Exact match, or the same topic phrased a little differently ("linear equations" vs "... by elimination")."""
    if key in _cache:
        return _cache[key]
    concept, curriculum, language = key
    words = _words(concept)
    for (c, cur, lang), value in _cache.items():
        other = _words(c)
        if cur == curriculum and lang == language and words and other:
            if len(words & other) / len(words | other) >= 0.5:
                return value
    return None


def _key_str(key: tuple) -> str:
    return "|".join(key)


def _load_disk_cache():
    """Found questions survive restarts, so a demo topic is instant once it has been searched."""
    try:
        with open(config.PRACTICE_CACHE_FILE) as f:
            for k, v in json.load(f).items():
                _cache[tuple(k.split("|"))] = Practice(**v)
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"  [nimble] ignoring unreadable cache ({e})", file=sys.stderr)


def _save_disk_cache():
    try:
        # every result, generated ones too (they're labeled), so a warmed demo topic is always instant;
        # delete practice_cache.json to search the web again
        data = {_key_str(k): v.model_dump() for k, v in _cache.items()}
        with open(config.PRACTICE_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        print(f"  [nimble] couldn't save cache ({e})", file=sys.stderr)


def _client():
    global _nimble
    if _nimble is None:
        from nimble_python import Nimble
        _nimble = Nimble(api_key=os.environ["NIMBLE_API_KEY"])
    return _nimble


def nimble_available() -> bool:
    return bool(os.environ.get("NIMBLE_API_KEY"))


def _field(item, name: str) -> str:
    """Nimble results may come back as objects or dicts."""
    value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
    return value or ""


def search_exam_pages(concept: str, curriculum: str) -> list[dict]:
    """Official past-paper sites first; if they return nothing, search the open web."""
    cur = config.CURRICULA[curriculum]
    pages = _search(cur["exam_query"].format(concept=concept), cur.get("exam_domains") or None)
    if not pages and cur.get("exam_domains"):
        print("  [nimble] nothing on past-paper sites, searching the open web", file=sys.stderr)
        pages = _search(cur["exam_query"].format(concept=concept), None)
    return pages


def _search(query: str, domains: list[str] | None) -> list[dict]:
    response = _client().search(
        query=query,
        max_results=config.NIMBLE_MAX_RESULTS,
        search_depth="standard",
        full_content=True,
        **({"include_domains": domains} if domains else {}),
    )
    results = response.get("results", []) if isinstance(response, dict) else getattr(response, "results", [])
    pages = []
    for r in results:
        text = _field(r, "content") or _field(r, "description")
        url = _field(r, "url")
        if text.strip() or url.lower().split("?")[0].endswith(".pdf"):
            pages.append({"url": url, "title": _field(r, "title"), "text": text})
    # Search often returns only a short summary of a PDF: download those and read the full text
    with obs.span("http.client", "read past-paper PDFs", count=len(pages)), ThreadPoolExecutor(max_workers=5) as pool:
        full = list(pool.map(_full_pdf_text, pages))
    for page, text in zip(pages, full):
        if text:
            page["text"] = text
        page["text"] = page["text"][: config.NIMBLE_CHARS_PER_PAGE]
    return [pg for pg in pages if pg["text"].strip()]


def _full_pdf_text(page: dict) -> str:
    """Full text of a PDF result whose search content is short. Empty string if it can't be read."""
    url = page["url"]
    if len(page["text"]) >= config.MIN_PAGE_CHARS or not url.lower().split("?")[0].endswith(".pdf"):
        return ""
    try:
        import httpx
        from pypdf import PdfReader
        # Hard deadline for the whole download: httpx's timeout is per chunk, so a server that
        # trickles data never trips it (Sentry caught necta.go.tz taking 3.6 minutes).
        deadline = time.time() + config.PDF_TIMEOUT_S
        data = bytearray()
        with httpx.stream("GET", url, timeout=config.PDF_TIMEOUT_S, follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                data.extend(chunk)
                if len(data) > config.PDF_MAX_BYTES:
                    return ""
                if time.time() > deadline:
                    raise TimeoutError(f"download took over {config.PDF_TIMEOUT_S}s")
        reader = PdfReader(io.BytesIO(bytes(data)))
        text = ""
        for pdf_page in reader.pages:
            text += (pdf_page.extract_text() or "") + "\n"
            if len(text) >= config.NIMBLE_CHARS_PER_PAGE:
                break
        return text.strip()  # scanned papers have no text layer: stays empty, keeps the short summary
    except Exception as e:  # noqa: BLE001
        print(f"    (couldn't read {url[:60]}: {str(e)[:60]})", file=sys.stderr)
        return ""


def find_practice(concept: str, problem: str, curriculum: str, language: str) -> Practice:
    """Real exam question if Nimble finds one, otherwise a clearly labeled Somo question. Cached per concept."""
    key = (concept.lower().strip(), curriculum, language)
    cached = _lookup(key)
    if cached:
        return cached
    start = time.time()
    cur = config.CURRICULA[curriculum]
    try:
        if not nimble_available():
            raise RuntimeError("no NIMBLE_API_KEY")
        with obs.span("http.client", "nimble search past papers", curriculum=curriculum) as sp:
            pages = search_exam_pages(concept, curriculum)
            if sp is not None:
                sp.set_data("pages", len(pages))
        print(f"  [nimble] {len(pages)} pages in {time.time() - start:.1f}s", file=sys.stderr)
        for pg in pages:
            print(f"    - {pg['title'][:70]}  ({len(pg['text'])} chars)  {pg['url'][:80]}", file=sys.stderr)
        if not pages:
            raise RuntimeError("no pages found")
        sources = "\n\n".join(f"[Source {i}] {p['title']} ({p['url']})\n{p['text']}" for i, p in enumerate(pages))
        picked, _ = llm.structured(
            prompts.PICK_EXAM_PROMPT.format(
                concept=concept, problem=problem, exam=cur["exam_label"], language=language, sources=sources),
            PickedQuestion,
        )
        if not picked.found or not (0 <= picked.source_index < len(pages)):
            raise RuntimeError("no suitable question in the pages")
        if not picked.same_concept:
            raise RuntimeError(f"closest question tests '{picked.question_concept}', not '{concept}'")
        page = pages[picked.source_index]
        kind = "past_exam" if picked.is_past_exam else "web"
        result = Practice(question=picked.question, expected_answer=picked.expected_answer, kind=kind, real=kind == "past_exam",
                          source_url=page["url"], source_title=page["title"],
                          exam_name=picked.exam_name if kind == "past_exam" else "",
                          seconds=round(time.time() - start, 1))
    except Exception as e:  # noqa: BLE001 — fall back to a Somo-written question, labeled as such
        print(f"  [nimble] falling back to a generated question ({str(e)[:80]})", file=sys.stderr)
        with obs.span("practice.fallback", "no usable past-paper question", reason=str(e)[:120]):
            pass
        q, _ = llm.structured(
            prompts.EXAM_STYLE_PROMPT.format(concept=concept, problem=problem, exam=cur["exam_label"], language=language),
            PickedQuestion,
        )
        result = Practice(question=q.question, expected_answer=q.expected_answer, kind="generated", real=False,
                          source_url="", source_title="", exam_name="", seconds=round(time.time() - start, 1))
    _cache[key] = result
    _save_disk_cache()
    return result


_load_disk_cache()


if __name__ == "__main__":
    # quick test: python practice.py "solving simultaneous linear equations" tanzania
    concept = sys.argv[1] if len(sys.argv) > 1 else "solving simultaneous linear equations by elimination"
    curriculum = sys.argv[2] if len(sys.argv) > 2 else "tanzania"
    print(find_practice(concept, "", curriculum, "English").model_dump_json(indent=2))