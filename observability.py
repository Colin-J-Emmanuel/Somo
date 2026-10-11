"""M6: Sentry tracing. Every Gemini, Claude, Gemma and Nimble call becomes a span.

Turned on only when SENTRY_DSN is set; without it, every helper here does nothing.
Student photos and prompt text are never sent to Sentry: only model names, timings and outcomes.
"""
import contextlib
import os

try:
    import sentry_sdk
except ImportError:  # Sentry is optional
    sentry_sdk = None

_enabled = False


def init() -> bool:
    global _enabled
    dsn = os.environ.get("SENTRY_DSN")
    if not (sentry_sdk and dsn):
        return False
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,      # trace every request: it's a demo, not production traffic
        send_default_pii=False,      # no student data
        environment=os.environ.get("SOMO_ENV", "hackathon"),
    )
    _enabled = True
    return True


@contextlib.contextmanager
def span(op: str, name: str, **data):
    """A timed step inside the current request or background task."""
    if not _enabled:
        yield None
        return
    with sentry_sdk.start_span(op=op, name=name) as s:
        for key, value in data.items():
            s.set_data(key, value)
        yield s


def background(name: str, fn, *args, **kwargs):
    """Run fn as its own Sentry transaction (background threads have no request around them)."""
    if not _enabled:
        return fn(*args, **kwargs)
    with sentry_sdk.start_transaction(op="task", name=name):
        return fn(*args, **kwargs)


def failover(label: str, error: Exception):
    """Record that Gemini failed and Claude took over (once per cooldown, so it isn't noisy)."""
    if not _enabled:
        return
    sentry_sdk.set_tag("failover", "gemini_to_claude")
    with sentry_sdk.new_scope() as scope:
        scope.set_tag("step", label)
        scope.set_extra("gemini_error", str(error)[:300])
        sentry_sdk.capture_message(f"Gemini unavailable, failed over to Claude ({label})", level="warning")


def error(e: Exception, **tags):
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        for key, value in tags.items():
            scope.set_tag(key, value)
        sentry_sdk.capture_exception(e)
