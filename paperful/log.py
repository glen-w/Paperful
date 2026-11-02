"""Process logging. Tokens are redacted before a record is emitted."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_BEARER = re.compile(r"(?i)\bbearer\s+\S+")
_SECRET = re.compile(r"(?i)\b(api[_-]?key|token|secret|authorization)\b(\s*[:=]\s*)\S+")

_configured = False


def redact(text: str) -> str:
    text = _BEARER.sub("Bearer [redacted]", text)

    def _sub(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}[redacted]"

    return _SECRET.sub(_sub, text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(
                redact(item) if isinstance(item, str) else item for item in record.args
            )
        return True


def configure(*, verbose: bool = False, log_file: Path | None = None) -> logging.Logger:
    """Install a redacting handler once. ``-v`` or ``PAPERFUL_VERBOSE=1`` is debug."""
    global _configured
    logger = logging.getLogger("paperful")
    if _configured:
        if verbose or os.environ.get("PAPERFUL_VERBOSE") == "1":
            logger.setLevel(logging.DEBUG)
        return logger
    level = (
        logging.DEBUG
        if verbose or os.environ.get("PAPERFUL_VERBOSE") == "1"
        else logging.WARNING
    )
    logger.setLevel(level)
    logger.addFilter(RedactFilter())
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    handler.addFilter(RedactFilter())
    logger.addHandler(handler)
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        file_handler.addFilter(RedactFilter())
        logger.addHandler(file_handler)
    logger.propagate = False
    _configured = True
    return logger


def get_logger(name: str) -> logging.Logger:
    configure()
    return logging.getLogger(name)
