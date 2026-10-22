"""Shim: completeness verbs live in dedicated ``*_cmd`` modules.

``cli.py`` and tests import ``run_*`` from here so monkeypatches on
``completeness_cmd.run_summarize`` (etc.) still intercept ``paperful summarize``.
"""

from __future__ import annotations

from .attachments_cmd import run_attachments
from .dedupe_cmd import run_dedupe
from .summarize_cmd import run_summarize
from .synthesize_cmd import run_synthesize

__all__ = ["run_dedupe", "run_attachments", "run_summarize", "run_synthesize"]
