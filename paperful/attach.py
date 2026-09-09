"""Attach downloaded PDFs to Zotero items through the Zotero 10+ local write API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import hashlib
import mimetypes
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

    def _get_auth(self, attachment: str, reg_key: str, md5: str | None = None) -> dict[str, Any]:
        att_path = Path(attachment)
        stat = att_path.stat()
        digest = hashlib.md5()  # noqa: S324
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
        req = self._post_with_retry(lambda: self.zinstance._write("POST", url=url, content=body, headers=headers))
        return req.json()


@dataclass
class AttachResult:
    ok: bool
    attachment_key: str | None = None
    reason: str = ""


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
        # The authorisation dialog blocks the HTTP response until the user clicks;
        # uploads of big PDFs also take a while. Reads are local and unaffected.
        try:
            self.zl.zot.client.timeout = DIALOG_TIMEOUT_S  # pyzotero vendors httpx; a float avoids type mixing
        except Exception:
            pass

    # ---- capability -------------------------------------------------------
    def supports_write(self) -> bool:
        if self._checked_write_support is None:
            try:
                self._checked_write_support = bool(self.zl.ping().get("supports_write"))
            except Exception:
                self._checked_write_support = False
        return self._checked_write_support

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
        except Exception as exc:  # dialog timed out, Zotero quit, vendored-httpx transport error
            raise AttachTransportError(f"authorisation failed: {type(exc).__name__}: {exc}") from exc
        if resp.get("remember"):
            self._store_key(resp["key"])
        return True

    # ---- attach -----------------------------------------------------------------
    def attach(self, item_key: str, pdf_path: Path, title: str | None = None) -> AttachResult:
        if not pdf_path.is_file():
            return AttachResult(False, reason=f"file missing: {pdf_path}")
        if not self.supports_write():
            return AttachResult(False, reason="Zotero local API has no write support (needs Zotero 10+)")
        for attempt in range(2):
            if not self.zl.zot.local_api_key:
                try:
                    granted = self.authorize()
                except AttachTransportError as exc:
                    return AttachResult(False, reason=str(exc))
                if not granted:
                    return AttachResult(False, reason="write authorisation denied in Zotero")
            try:
                # attachment_simple() needs the /items/new template endpoint, which the local
                # API does not serve; build the stored-file attachment item ourselves.
                payload = [attachment_payload(pdf_path, title)]
                result = LocalZupload(self.zl.zot, payload, item_key, basedir=str(pdf_path.parent)).upload()
            except (ze.LocalAPIKeyRequiredError, ze.UserNotAuthorisedError) as exc:
                # single-use key consumed, or revoked in Zotero settings
                self._forget_key()
                if attempt == 1:
                    return AttachResult(False, reason=f"unauthorised: {exc}")
                continue
            except ze.TooManyRequestsError:
                return AttachResult(False, reason="Zotero rate-limited authorisation prompts; wait a minute")
            except ze.PyZoteroError as exc:
                return AttachResult(False, reason=f"{type(exc).__name__}: {exc}")
            except Exception as exc:  # transport errors from pyzotero's vendored httpx
                return AttachResult(False, reason=f"{type(exc).__name__}: {exc}")
            return _interpret(result)
        return AttachResult(False, reason="gave up")


def attachment_payload(pdf_path: Path, title: str | None = None) -> dict:
    """A stored-file attachment item as the Zotero write API expects it (no template needed)."""
    return {
        "itemType": "attachment",
        "linkMode": "imported_file",
        "title": title or "Full Text PDF",
        "filename": pdf_path.name,
        "contentType": "application/pdf",
        "charset": "",
        "accessDate": "",
        "note": "",
        "tags": [],
        "relations": {},
    }


def _interpret(result: dict) -> AttachResult:
    for bucket in ("success", "unchanged"):
        for entry in result.get(bucket) or []:
            return AttachResult(True, attachment_key=entry.get("key"), reason=bucket)
    for entry in result.get("failure") or []:
        return AttachResult(False, reason=str(entry.get("error") or "upload failed"))
    return AttachResult(False, reason="no result from Zotero")
