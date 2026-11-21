"""Optional model-backed AI-text score for critique.

Not a core dependency. Tries Binoculars (Hans et al., ICML 2024) if
installed (git overlay, not a locked extra); otherwise returns None so the
pack can record ``ai_model_unavailable``. Never used as proof of authorship.
"""

from __future__ import annotations

import importlib.util
import multiprocessing
import os
import sys
from typing import Any

_OFFLINE_ENV = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
# Cached Falcon load is usually seconds. A Hugging Face download of the
# performer checkpoint can stall for tens of minutes and must not block
# reviewers / MARG.
DEFAULT_TIMEOUT_S = 90.0


def extra_available() -> bool:
    """True when the Binoculars extra can be imported. Does not load torch."""
    if "binoculars" in sys.modules:
        return True
    try:
        return importlib.util.find_spec("binoculars") is not None
    except ValueError:
        return False


def _compute_score(text: str) -> dict[str, Any] | None:
    """Run Binoculars in-process. Hugging Face stays offline."""
    try:
        from binoculars import Binoculars  # type: ignore
    except ImportError:
        return None
    prev = {key: os.environ.get(key) for key in _OFFLINE_ENV}
    for key in _OFFLINE_ENV:
        os.environ[key] = "1"
    try:
        bino = Binoculars()
        raw = bino.compute_score(text)
    except Exception:
        return None
    finally:
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if isinstance(raw, (list, tuple)):
        if not raw:
            return None
        raw = raw[0]
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return None
    return {"backend": "binoculars", "score": score}


def _worker(text: str, conn: Any) -> None:
    try:
        conn.send(_compute_score(text))
    except Exception:
        conn.send(None)
    finally:
        conn.close()


def run_ai_model(
    text: str, timeout_s: float = DEFAULT_TIMEOUT_S
) -> dict[str, Any] | None:
    """Return ``{backend, score}`` or None if the extra is missing / fails.

    Loads Binoculars in a child process and kills it if it exceeds
    ``timeout_s`` so a weight download cannot stall the critique pack.
    ``timeout_s <= 0`` runs in-process (tests).
    """
    if not extra_available():
        return None
    if timeout_s <= 0:
        return _compute_score(text)
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_worker, args=(text, child), daemon=True)
    proc.start()
    child.close()
    try:
        if parent.poll(timeout_s):
            try:
                return parent.recv()
            except EOFError:
                return None
        proc.terminate()
        proc.join(5)
        if proc.is_alive():
            proc.kill()
            proc.join(2)
        return None
    finally:
        parent.close()
        if proc.is_alive():
            proc.kill()
            proc.join(2)
