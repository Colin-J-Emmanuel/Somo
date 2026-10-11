"""In-memory session store. One session per snapped photo. Resets when the server restarts."""
import uuid

SESSIONS: dict[str, dict] = {}


def create(**data) -> str:
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"attempts": [], "mastery": {}, **data}
    return sid


def get(sid: str) -> dict:
    return SESSIONS[sid]  # KeyError -> the route turns it into a 404


def record_attempt(session: dict, question: str, answer: str, correct: bool):
    session["attempts"].append({"question": question, "answer": answer, "correct": correct})
    concept = session["diagnosis"].concept
    m = session["mastery"].setdefault(concept, {"correct": 0, "attempts": 0})
    m["attempts"] += 1
    m["correct"] += int(correct)
