"""Attach downloaded PDFs to Zotero items through the Zotero 10+ local write API."""

from __future__ import annotations

import hashlib
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from pyzotero import errors as ze
from pyzotero._upload import Zupload
from pyzotero._utils import build_url

from .config import Config
from .zot import ZoteroLocal

DIALOG_TIMEOUT_S = 600.0


class AttachTransportError(Exception):
    pass


class LocalZupload(Zupload):
    """Zupload whose step-1 body encodes spaces as %20.

    pyzotero sends step 1 as application/x-www-form-urlencoded, where spaces become '+'.
    Zotero's local upload endpoint only percent-decodes, so a filename like
    'Aron - 1990 - Title.pdf' would be stored as 'Aron+-+1990+-+Title.pdf'.
    """

    def _get_auth(
        self, attachment: str, reg_key: str, md5: str | None = None
    ) -> dict[str, Any]:
        att_path = Path(attachment)
        stat = att_path.stat()
        digest = hashlib.md5()
        with att_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                digest.update(chunk)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        headers["If-Match" if md5 else "If-None-Match"] = md5 or "*"
        data = {
            "md5": digest.hexdigest(),
            "filename": att_path.name,
            "filesize": stat.st_size,
            "mtime": str(int(stat.st_mtime * 1000)),
            "contentType": mimetypes.guess_type(attachment)[0] or "application/pdf",
            "params": 1,
        }
        body = urlencode(data, quote_via=quote)
        url = build_url(
            self.zinstance.endpoint,
            f"/{self.zinstance.library_type}/{self.zinstance.library_id}/items/{reg_key}/file",
        )
        req = self._post_with_retry(
            lambda: self.zinstance._write(
                "POST", url=url, content=body, headers=headers
            )
        )
        return req.json()


ATTACH_CODES = frozenset(
    {
        "success",
        "unchanged",
        "quota",
        "no_write_api",
        "auth",
        "parent_missing",
        "other",
    }
)


def parent_missing(reason: str) -> bool:
    """Zotero rejected the upload because the parent item key is gone (often after sync remaps)."""
    low = reason.lower()
    return "parent item" in low and "not found" in low


def attach_failure_code(reason: str) -> str:
    low = reason.lower()
    if "write support" in low or "zotero 10" in low or "needs zotero 10" in low:
        return "no_write_api"
    if "quota" in low or "storage" in low or "limit exceeded" in low:
        return "quota"
    if "auth" in low or "unauthor" in low or "denied" in low:
        return "auth"
    if parent_missing(reason):
        return "parent_missing"
    return "other"


@dataclass
class AttachResult:
    ok: bool
    attachment_key: str | None = None
    reason: str = ""
    code: str = ""


class Attacher:
    """Holds one authorised local client; re-authorises on demand."""

    def __init__(self, cfg: Config, zl: ZoteroLocal | None = None):
        self.cfg = cfg
        self.key_path = cfg.local_key_path
        stored = self._load_key()
        self.zl = zl or ZoteroLocal(local_api_key=stored)
        if stored and not self.zl.zot.local_api_key:
            self.zl.zot.local_api_key = stored
        self._checked_write_support: bool | None = None
        self._write_block_reason = ""
        # The authorisation dialog blocks the HTTP response until the user clicks;
        # uploads of big PDFs also take a while. Reads are local and unaffected.
        try:
            self.zl.zot.client.timeout = (
                DIALOG_TIMEOUT_S  # pyzotero vendors httpx; a float avoids type mixing
            )
        except Exception:
            pass

    # ---- capability -------------------------------------------------------
    def supports_write(self) -> bool:
        if self._checked_write_support is None:
            self._write_block_reason = ""
            try:
                info = self.zl.ping()
                self._checked_write_support = bool(info.get("supports_write"))
                if not self._checked_write_support:
                    version = info.get("zotero_version") or "unknown"
                    self._write_block_reason = (
                        f"Zotero {version} local API has no write support (needs Zotero 10+)"
                    )
            except Exception as exc:
                self._checked_write_support = False
                self._write_block_reason = (
                    f"Could not check Zotero write support: {type(exc).__name__}: {exc}"
                )
        return self._checked_write_support

    def write_block_reason(self) -> str:
        self.supports_write()
        return self._write_block_reason or (
            "Zotero local API has no write support (needs Zotero 10+)"
        )

    # ---- key persistence --------------------------------------------------
    def _load_key(self) -> str | None:
        try:
            data = json.loads(self.key_path.read_text())
            return data.get("key") or None
        except (OSError, ValueError):
            return None

    def _store_key(self, key: str) -> None:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        self.key_path.write_text(json.dumps({"key": key}))
        try:
            self.key_path.chmod(0o600)
        except OSError:
            pass

    def _forget_key(self) -> None:
        self.zl.zot.local_api_key = None
        try:
            self.key_path.unlink()
        except OSError:
            pass

    def authorize(self) -> bool:
        """Ask Zotero for a write key (shows a dialog). Returns True if granted."""
        try:
            resp = self.zl.zot.authorize_local(self.cfg.app_name)
        except ze.LocalAPIDeniedError:
            return False
        except (
            Exception
        ) as exc:  # dialog timed out, Zotero quit, vendored-httpx transport error
            raise AttachTransportError(
                f"authorisation failed: {type(exc).__name__}: {exc}"
            ) from exc
        if resp.get("remember"):
            self._store_key(resp["key"])
        return True

    # ---- attach -----------------------------------------------------------------
    def attach(
        self,
        item_key: str,
        pdf_path: Path,
        title: str | None = None,
        note: str | None = None,
    ) -> AttachResult:
        if not pdf_path.is_file():
            return AttachResult(False, reason=f"file missing: {pdf_path}", code="other")
        if not self.supports_write():
            reason = self.write_block_reason()
            return AttachResult(
                False,
                reason=reason,
                code=attach_failure_code(reason),
            )
        for attempt in range(2):
            if not self.zl.zot.local_api_key:
                try:
                    granted = self.authorize()
                except AttachTransportError as exc:
                    msg = str(exc)
                    return AttachResult(
                        False, reason=msg, code=attach_failure_code(msg)
                    )
                if not granted:
                    return AttachResult(
                        False,
                        reason="write authorisation denied in Zotero",
                        code="auth",
                    )
            try:
                # attachment_simple() needs the /items/new template endpoint, which the local
                # API does not serve; build the stored-file attachment item ourselves.
                payload = [attachment_payload(pdf_path, title, note=note)]
                result = LocalZupload(
                    self.zl.zot, payload, item_key, basedir=str(pdf_path.parent)
                ).upload()
            except (ze.LocalAPIKeyRequiredError, ze.UserNotAuthorisedError) as exc:
                # single-use key consumed, or revoked in Zotero settings
                self._forget_key()
                if attempt == 1:
                    msg = f"unauthorised: {exc}"
                    return AttachResult(False, reason=msg, code="auth")
                continue
            except ze.TooManyRequestsError:
                return AttachResult(
                    False,
                    reason="Zotero rate-limited authorisation prompts; wait a minute",
                    code="other",
                )
            except ze.PyZoteroError as exc:
                msg = f"{type(exc).__name__}: {exc}"
                return AttachResult(False, reason=msg, code=attach_failure_code(msg))
            except Exception as exc:  # transport errors from pyzotero's vendored httpx
                msg = f"{type(exc).__name__}: {exc}"
                return AttachResult(False, reason=msg, code=attach_failure_code(msg))
            return _interpret(result)
        return AttachResult(False, reason="gave up", code="other")


def attachment_payload(
    pdf_path: Path, title: str | None = None, note: str | None = None
) -> dict:
    """A stored-file attachment item as the Zotero write API expects it (no template needed).

    ``contentType`` is guessed from the filename so image thumbnails (``image/jpeg``)
    work the same path as PDFs. Default title stays ``Full Text PDF`` for PDF
    attachers; pass ``title=\"thumbnail\"`` for library preview images.
    """
    guessed = mimetypes.guess_type(pdf_path.name)[0] or "application/pdf"
    default_title = "Full Text PDF" if guessed == "application/pdf" else pdf_path.stem
    return {
        "itemType": "attachment",
        "linkMode": "imported_file",
        "title": title or default_title,
        "filename": pdf_path.name,
        "contentType": guessed,
        "charset": "",
        "accessDate": "",
        "note": note or "",
        "tags": [],
        "relations": {},
    }


def _interpret(result: dict) -> AttachResult:
    for bucket in ("success", "unchanged"):
        for entry in result.get(bucket) or []:
            return AttachResult(
                True, attachment_key=entry.get("key"), reason=bucket, code=bucket
            )
    for entry in result.get("failure") or []:
        msg = str(entry.get("error") or "upload failed")
        return AttachResult(False, reason=msg, code=attach_failure_code(msg))
    return AttachResult(False, reason="no result from Zotero", code="other")
