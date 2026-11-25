"""
Saved plans (the Chart Planner's Save, Load, Rename and Delete): a finished plan, its form settings (`params`) and its
result, kept as files in `planner-saves/` next to config.json, so they survive a restart and an update. Files only:
no web, no Planner; web/planner_saves.py decides what may be saved and loaded and when.

One file per plan, named `<id>.jsonl` with the id `YYYYMMDD-HHMMSS-<8 hex digits>` (UTC). The name the user typed is
only text inside the file, so no name can reach a path. The file is two lines of JSON:

    {"format": 1, "id", "name", "saved_at", "summary": {...}}      the header: all a listing reads
    {"params": {...}, "result": {...}}                              the body, read only by a Load

A listing reads one short line of each file, never a whole plan. Writes are atomic (a new file next to it, moved into
place, mode 0644) and made under a lock; a file that is not exactly this shape (hand-edited, too big, cut short, the
wrong id) is ignored, never an error. Nothing here raises except SaveError, which carries the reason and a sentence.
"""

import contextlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

FOLDER = "planner-saves"
SUFFIX = ".jsonl"
FORMAT = 1
MAX_SAVES = 50  # plans kept: the folder never grows past this
MAX_NAME = 60  # characters in a name
MAX_BYTES = 8 * 1024 * 1024  # one file: a 1000-airport plan is about 1 MB; a bigger file is not one of ours
MAX_HEADER = 8 * 1024  # the header line
ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")


class SaveError(Exception):
    """A refusal: `reason` is the short code the API answers with, `status` its HTTP status, str(e) the sentence."""

    def __init__(self, reason: str, message: str, status: int = 409):
        super().__init__(message)
        self.reason, self.status = reason, status


def clean_name(name: Any) -> str:
    """
    The name as it is kept: text, NFC, with the spaces around it and between its words reduced to one space each.
    Raises SaveError("invalid") for no name, one over MAX_NAME characters, a / or \\, or a control, format or line
    separator character. The name is only ever text in the file (the file's name is the id), so there is no reserved
    name or other path trouble to avoid; the slashes are refused so a name never looks like a path in a message.
    """
    if not isinstance(name, str):
        raise SaveError("invalid", "The plan needs a name", 400)
    text = unicodedata.normalize("NFC", name)
    for char in text:
        if char in "/\\" or unicodedata.category(char) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            raise SaveError("invalid", "The name cannot have slashes, line breaks or other control characters", 400)
    text = " ".join(text.split())  # the spaces (any kind) around it and between its words become one each
    if not text:
        raise SaveError("invalid", "The plan needs a name", 400)
    if len(text) > MAX_NAME:
        raise SaveError("invalid", f"The name can be at most {MAX_NAME} characters", 400)
    return text


def name_key(name: str) -> str:
    """What two names are compared by: case and accents' composition ignored (the Houston and houston plans clash)."""
    return unicodedata.normalize("NFC", name).casefold()


def valid_id(plan_id: Any) -> bool:
    return isinstance(plan_id, str) and bool(ID.match(plan_id))


def _read_line(path: str, limit: int) -> Optional[bytes]:
    """The first line of a file, or None when it is missing, not a file, too big, or its line is longer than limit."""
    try:
        if os.path.getsize(path) > MAX_BYTES or not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            line = f.readline(limit + 1)
    except OSError:
        return None
    return line if len(line) <= limit else None


def _loads(raw: bytes) -> Any:
    """JSON from bytes, or None: a number too big, nesting too deep, bad UTF-8 or a plain syntax error is no data."""
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError, MemoryError):
        return None


def _header_ok(header: Any, plan_id: str) -> bool:
    return (
        isinstance(header, dict)
        and header.get("id") == plan_id
        and isinstance(header.get("name"), str)
        and 0 < len(header["name"]) <= MAX_NAME * 4
        and isinstance(header.get("saved_at"), str)
        and isinstance(header.get("summary"), dict)
        and isinstance(header.get("format"), int)
        and not isinstance(header.get("format"), bool)
    )


class PlanSaves:
    """The saved plans in one folder (see the module doc). Safe to use from several threads."""

    def __init__(self, folder: str):
        self.folder = folder
        self._lock = threading.Lock()

    # ---- reading ----------------------------------------------------------------------------------------------

    def _path(self, plan_id: str) -> str:
        return os.path.join(self.folder, plan_id + SUFFIX)

    def _ids(self) -> List[str]:
        try:
            names = os.listdir(self.folder)
        except OSError:
            return []
        return [n[: -len(SUFFIX)] for n in names if n.endswith(SUFFIX) and valid_id(n[: -len(SUFFIX)])]

    def _header(self, plan_id: str) -> Optional[Dict[str, Any]]:
        line = _read_line(self._path(plan_id), MAX_HEADER)
        header = _loads(line) if line else None
        return header if _header_ok(header, plan_id) else None

    def listing(self) -> List[Dict[str, Any]]:
        """The plans that can be read, newest first: [{"id", "name", "saved_at", "format", "summary"}]. Never raises."""
        found = []
        for plan_id in self._ids():
            header = self._header(plan_id)
            if header:
                found.append({k: header[k] for k in ("id", "name", "saved_at", "format", "summary")})
        return sorted(found, key=lambda h: (h["saved_at"], h["id"]), reverse=True)

    def read(self, plan_id: Any) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """
        (header, params, result) of a saved plan. Raises SaveError: "not_found" (404) for no such plan, "unreadable"
        (409) for a file that is cut short, edited, too big or not what a plan is, "format" (409) for one saved in a
        format this version does not know.
        """
        if not valid_id(plan_id):
            raise SaveError("not_found", "There is no saved plan with that id", 404)
        path = self._path(plan_id)
        if not os.path.isfile(path):
            raise SaveError("not_found", "There is no saved plan with that id", 404)
        bad = SaveError("unreadable", "That saved plan cannot be read: its file is damaged", 409)
        try:
            if os.path.getsize(path) > MAX_BYTES:
                raise bad
            with open(path, "rb") as f:
                head = f.readline(MAX_HEADER + 1)
                rest = f.readline(MAX_BYTES + 1)
        except OSError as e:
            log.warning(f"could not read the saved plan {plan_id}: {e}")
            raise bad from None
        header, body = _loads(head), _loads(rest)
        if not _header_ok(header, plan_id) or not isinstance(body, dict):
            raise bad
        if header["format"] != FORMAT:
            raise SaveError(
                "format", "That plan was saved by a different version of MetarMap2 and cannot be loaded here", 409
            )
        if not isinstance(body.get("params"), dict) or not isinstance(body.get("result"), dict):
            raise bad
        return header, body["params"], body["result"]

    # ---- writing ----------------------------------------------------------------------------------------------

    def _write(self, plan_id: str, head: bytes, body: bytes) -> None:
        """Writes the file whole beside its place and moves it there: a reader never sees half of one."""
        temporary = None
        try:
            os.makedirs(self.folder, exist_ok=True)
            handle, temporary = tempfile.mkstemp(dir=self.folder, prefix=".save-", suffix=".tmp")
            with os.fdopen(handle, "wb") as f:
                f.write(head + b"\n" + body + b"\n")
            os.chmod(temporary, 0o644)  # mkstemp makes it private
            os.replace(temporary, self._path(plan_id))
            temporary = None
        except OSError as e:
            log.warning(f"could not write the saved plan {plan_id}: {e}")
            raise SaveError("failed", "Could not write the saved plan: nothing changed", 500) from None
        finally:
            if temporary:
                with contextlib.suppress(OSError):
                    os.remove(temporary)

    def save(
        self, name: Any, params: Dict[str, Any], result: Dict[str, Any], summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Keeps a plan under `name`. Raises SaveError: "invalid" (400) for a bad name, "exists" (409) when a plan has
        that name already (compared without case: nothing is overwritten, delete or rename the old one), "full" (409)
        at MAX_SAVES plans, "too_big" (409) for a plan over MAX_BYTES, "failed" (500) when the file cannot be written.
        Returns the listing entry.
        """
        name = clean_name(name)
        try:
            body = json.dumps({"params": params, "result": result}, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            raise SaveError("failed", "The plan cannot be saved", 500) from None
        if len(body) > MAX_BYTES - MAX_HEADER - 2:
            raise SaveError("too_big", "The plan is too big to save", 409)
        with self._lock:
            existing = self.listing()
            if any(name_key(e["name"]) == name_key(name) for e in existing):
                raise SaveError("exists", f"A saved plan called {name} already exists: pick another name", 409)
            if len(existing) >= MAX_SAVES:
                raise SaveError("full", f"{MAX_SAVES} plans are saved already: delete one first", 409)
            now = datetime.now(timezone.utc).replace(microsecond=0)
            plan_id = f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(4)}"
            header = {
                "format": FORMAT,
                "id": plan_id,
                "name": name,
                "saved_at": now.isoformat(),
                "summary": summary,
            }
            head = json.dumps(header, separators=(",", ":")).encode("utf-8")
            if len(head) > MAX_HEADER:
                raise SaveError("too_big", "The plan's summary is too big to save", 409)
            self._write(plan_id, head, body)
        return {k: header[k] for k in ("id", "name", "saved_at", "format", "summary")}

    def rename(self, plan_id: Any, name: Any) -> Dict[str, Any]:
        """
        Gives a plan another name. Raises SaveError: "invalid", "not_found" (404), "exists" (a different plan has the
        name; the same plan with another case is fine), "unreadable", "failed". Returns the listing entry.
        """
        name = clean_name(name)
        if not valid_id(plan_id):
            raise SaveError("not_found", "There is no saved plan with that id", 404)
        with self._lock:
            path = self._path(plan_id)
            if not os.path.isfile(path):
                raise SaveError("not_found", "There is no saved plan with that id", 404)
            header = self._header(plan_id)
            if header is None:
                raise SaveError("unreadable", "That saved plan cannot be read: its file is damaged", 409)
            if any(e["id"] != plan_id and name_key(e["name"]) == name_key(name) for e in self.listing()):
                raise SaveError("exists", f"A saved plan called {name} already exists: pick another name", 409)
            try:
                with open(path, "rb") as f:
                    f.readline(MAX_HEADER + 1)
                    body = f.readline(MAX_BYTES + 1).rstrip(b"\n")
            except OSError as e:
                log.warning(f"could not read the saved plan {plan_id}: {e}")
                raise SaveError("unreadable", "That saved plan cannot be read: its file is damaged", 409) from None
            header["name"] = name
            self._write(plan_id, json.dumps(header, separators=(",", ":")).encode("utf-8"), body)
        return {k: header[k] for k in ("id", "name", "saved_at", "format", "summary")}

    def delete(self, plan_id: Any) -> None:
        """Removes a plan's file (also one that cannot be read, so a damaged file can be cleared). Raises SaveError
        "not_found" (404) or "failed"."""
        if not valid_id(plan_id):
            raise SaveError("not_found", "There is no saved plan with that id", 404)
        with self._lock:
            try:
                os.remove(self._path(plan_id))
            except FileNotFoundError:
                raise SaveError("not_found", "There is no saved plan with that id", 404) from None
            except OSError as e:
                log.warning(f"could not delete the saved plan {plan_id}: {e}")
                raise SaveError("failed", "Could not delete the saved plan", 500) from None
