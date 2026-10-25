"""MailFlow Studio - helpers for the Compose page.

Two jobs live here:

1. Attachments. Files are checked, then kept in a private "draft" folder on
   this computer between "Preview" and "Confirm & send", so the person does
   not have to pick them again. The folder is deleted after sending, and old
   ones are cleaned up automatically.
2. Importing email addresses from a small .csv or .txt file.

Nothing here talks to the network, and nothing here serves files back to a
browser.
"""

import mimetypes
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from werkzeug.utils import secure_filename

MAX_FILES = 5
MAX_TOTAL_BYTES = 10 * 1024 * 1024          # 10 MB for all files together
MAX_ADDRESS_FILE_BYTES = 200 * 1024         # a list of addresses is tiny
DRAFT_MAX_AGE_SECONDS = 24 * 60 * 60        # abandoned drafts are removed

# What each allowed file type must start with. A file renamed from .exe to
# .pdf fails this check.
_PDF = (b"%PDF",)
_PNG = (b"\x89PNG\r\n\x1a\n",)
_JPG = (b"\xff\xd8\xff",)
_ZIP = (b"PK\x03\x04",)                      # docx, xlsx, pptx
_OLE = (b"\xd0\xcf\x11\xe0",)                # old doc, xls, ppt
_TEXT = None                                 # txt and csv: checked separately

ALLOWED_TYPES = {
    "pdf": _PDF, "png": _PNG, "jpg": _JPG, "jpeg": _JPG,
    "docx": _ZIP, "xlsx": _ZIP, "pptx": _ZIP,
    "doc": _OLE, "xls": _OLE, "ppt": _OLE,
    "txt": _TEXT, "csv": _TEXT,
}

ACCEPT_ATTRIBUTE = ",".join("." + ext for ext in sorted(ALLOWED_TYPES))
ALLOWED_LABEL = "PDF, Word, Excel, PowerPoint, TXT, CSV, JPG, PNG"

_DRAFT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_STORED_RE = re.compile(r"^(\d{2})__(.+)$")


def format_size(size):
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


# ---------------- Draft folders ----------------

def new_draft_id():
    return secrets.token_hex(16)


def is_valid_draft_id(value):
    return bool(_DRAFT_ID_RE.fullmatch(value or ""))


def draft_dir(base_dir, user_id, draft_id):
    """Folder for one draft. The user's id is part of the path, so one
    person can never reach another person's files."""
    if not is_valid_draft_id(draft_id):
        raise ValueError("Invalid draft id.")
    return Path(base_dir) / "drafts" / str(int(user_id)) / draft_id


def list_files(directory):
    """Files in a draft, in the order they were added."""
    directory = Path(directory)
    if not directory.is_dir():
        return []

    files = []
    for entry in sorted(directory.iterdir()):
        match = _STORED_RE.match(entry.name)
        if match and entry.is_file():
            files.append(
                {
                    "stored": entry.name,
                    "name": match.group(2),
                    "size": entry.stat().st_size,
                    "size_text": format_size(entry.stat().st_size),
                }
            )
    return files


def delete_draft(directory):
    shutil.rmtree(directory, ignore_errors=True)


def delete_files(directory, stored_names):
    """Remove chosen files. Only names that really are in the draft count,
    so a made-up name cannot point anywhere else."""
    wanted = set(stored_names)
    removed = 0
    for item in list_files(directory):
        if item["stored"] in wanted:
            try:
                (Path(directory) / item["stored"]).unlink()
                removed += 1
            except OSError:
                pass
    return removed


def cleanup_old_drafts(base_dir, user_id, now=None):
    """Delete this user's drafts that were last touched over a day ago."""
    root = Path(base_dir) / "drafts" / str(int(user_id))
    if not root.is_dir():
        return
    now = time.time() if now is None else now
    for entry in root.iterdir():
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > DRAFT_MAX_AGE_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass


# ---------------- Checking uploads ----------------

def _split_name(filename):
    """Return (stem, extension) from the name the browser sent."""
    last = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem, ext = os.path.splitext(last)
    return stem, ext.lstrip(".").lower()


def clean_name(filename):
    """A safe name that keeps the real extension (even for Urdu file names,
    which secure_filename alone would strip down to nothing)."""
    stem, ext = _split_name(filename)
    stem = secure_filename(stem).strip("._ ")[:80] or "attachment"
    return f"{stem}.{ext}"


def check_file(filename, data):
    """Return a plain-language problem, or None if the file is fine."""
    shown = (filename or "file")[:60]
    stem, ext = _split_name(filename)

    if ext not in ALLOWED_TYPES:
        return f'"{shown}" is not an allowed file type. Allowed: {ALLOWED_LABEL}.'
    if not data:
        return f'"{shown}" is empty.'

    signatures = ALLOWED_TYPES[ext]
    if signatures is None:
        if b"\x00" in data[:8192]:
            return f'"{shown}" does not look like a text file.'
    elif not data.startswith(signatures):
        return f'"{shown}" does not look like a real .{ext} file.'
    return None


def add_files(directory, uploads):
    """Check every upload, then save them all together.

    Nothing is saved unless every file passes, so the person gets one clear
    message instead of half an upload. Returns (saved_count, problems).
    """
    directory = Path(directory)
    existing = list_files(directory)
    problems = []

    if len(existing) + len(uploads) > MAX_FILES:
        return 0, [f"You can attach up to {MAX_FILES} files in one email."]

    used = sum(item["size"] for item in existing)
    accepted = []

    for upload in uploads:
        data = upload.read(MAX_TOTAL_BYTES + 1)
        problem = check_file(upload.filename, data)
        if problem:
            problems.append(problem)
            continue
        used += len(data)
        accepted.append((clean_name(upload.filename), data))

    if used > MAX_TOTAL_BYTES:
        problems.append(
            f"The attachments are too large. The total limit is {format_size(MAX_TOTAL_BYTES)}."
        )

    if problems:
        return 0, problems

    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        directory.chmod(0o700)
    number = max([int(_STORED_RE.match(i["stored"]).group(1)) for i in existing] + [0])

    for name, data in accepted:
        number += 1
        stored_path = directory / f"{number:02d}__{name}"
        stored_path.write_bytes(data)
        if os.name == "posix":
            stored_path.chmod(0o600)

    return len(accepted), []


def read_attachments(directory):
    """Return [(file name, bytes, maintype, subtype)] ready to attach."""
    result = []
    total = 0
    for item in list_files(directory):
        data = (Path(directory) / item["stored"]).read_bytes()
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ValueError("The attachments are too large to send.")
        mime = mimetypes.guess_type(item["name"])[0] or "application/octet-stream"
        maintype, _, subtype = mime.partition("/")
        result.append((item["name"], data, maintype, subtype or "octet-stream"))
    return result


# ---------------- Importing addresses from a file ----------------

_ADDRESS_TOKEN = re.compile(r"[^\s,;\"'<>()\[\]]+@[^\s,;\"'<>()\[\]]+")


def read_address_file(upload):
    """Read a small .csv or .txt upload. Returns (text, problem)."""
    _stem, ext = _split_name(upload.filename)
    if ext not in ("csv", "txt"):
        return "", "Choose a .csv or .txt file for the address list."

    data = upload.read(MAX_ADDRESS_FILE_BYTES + 1)
    if len(data) > MAX_ADDRESS_FILE_BYTES:
        return "", "That address file is too large. Keep it under 200 KB."
    if b"\x00" in data[:8192]:
        return "", "That does not look like a text or CSV file."
    return data.decode("utf-8-sig", errors="replace"), None


def extract_addresses(text, is_valid):
    """Find email addresses in free text or CSV cells.

    Returns (addresses without duplicates, number of look-alikes skipped).
    """
    found, seen, skipped = [], set(), 0
    for token in _ADDRESS_TOKEN.findall(text or ""):
        token = token.strip(".:-")
        if not is_valid(token):
            skipped += 1
            continue
        key = token.casefold()
        if key not in seen:
            seen.add(key)
            found.append(token)
    return found, skipped
