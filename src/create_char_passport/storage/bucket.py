"""Bucket-rooted filesystem operations.

Storage layout (rooted at ``settings.bucket_path``)::

    <bucket>/
      <character_id>/
        state.json
        refs/<step_key>.png       # last / approved generations
        approved/<name>.png       # final dataset archive
        rejected/<step_key>_attempt<N>.png

Rules baked in here:

* Paths inside ``state.json`` are *relative* to the character folder
  (portable across host / bucket moves).
* Rejected frames are never deleted — when a step is regenerated, the
  previous frame moves to ``rejected/`` with the next free attempt number.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from create_char_passport.config import get_settings
from create_char_passport.state import CharacterState, state_from_dict, state_to_dict

STATE_FILENAME = "state.json"
REFS_DIR = "refs"
APPROVED_DIR = "approved"
REJECTED_DIR = "rejected"


def bucket_root() -> Path:
    """Resolved bucket root, created on demand."""
    root = Path(get_settings().bucket_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def character_dir(character_id: str, *, root: Path | None = None) -> Path:
    """Folder for one character, with refs/approved/rejected ensured."""
    base = (root or bucket_root()) / character_id
    for sub in (REFS_DIR, APPROVED_DIR, REJECTED_DIR):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def character_asset(character_id: str, rel_path: str, *, root: Path | None = None) -> Path:
    """Absolute path of a character-relative asset (e.g. ``refs/passport_face.png``).

    Inverse of the "paths in ``state.json`` are relative to the character folder"
    rule: callers store the relative path, then resolve it here to a real path
    for the generator (reading a ref) or the UI (showing a preview). Unlike
    :func:`character_dir` it does not create sub-folders — it only joins a path.
    """
    return (root or bucket_root()) / character_id / rel_path


def save_state(state: CharacterState, *, root: Path | None = None) -> Path:
    """Write ``state.json`` for ``state`` atomically and return its path."""
    folder = character_dir(state.character_id, root=root)
    target = folder / STATE_FILENAME
    tmp = target.with_suffix(".json.tmp")
    payload = json.dumps(state_to_dict(state), indent=2, ensure_ascii=False, sort_keys=True)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)
    return target


def load_state(character_id: str, *, root: Path | None = None) -> CharacterState | None:
    """Load a character's state, or ``None`` if no ``state.json`` exists yet."""
    target = (root or bucket_root()) / character_id / STATE_FILENAME
    if not target.is_file():
        return None
    data = json.loads(target.read_text(encoding="utf-8"))
    return state_from_dict(data)


def list_character_ids(*, root: Path | None = None) -> list[str]:
    """All character ids with a saved ``state.json``, sorted for stability."""
    base = root or bucket_root()
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and (p / STATE_FILENAME).is_file())


def next_attempt_number(rejected_dir: Path, step_key: str) -> int:
    """Smallest unused ``<step_key>_attempt<N>`` suffix (N starts at 1)."""
    prefix = f"{step_key}_attempt"
    used = {
        int(p.stem[len(prefix) :])
        for p in rejected_dir.glob(f"{prefix}*.*")
        if p.stem[len(prefix) :].isdigit()
    }
    n = 1
    while n in used:
        n += 1
    return n


def save_to_approved(character_path: Path, name: str, frame: Path) -> Path:
    """Copy ``frame`` into ``approved/<name>.png`` (the final dataset archive, §5).

    Copies (not moves) so the working ``refs/`` frame stays as the preview; a
    re-approval of the same composition overwrites its approved image. Returns
    the destination path. No-op returning the destination when ``frame`` is absent.
    """
    approved = character_path / APPROVED_DIR
    approved.mkdir(parents=True, exist_ok=True)
    destination = approved / f"{name}{frame.suffix}"
    if frame.exists():
        shutil.copy(str(frame), destination)
    return destination


def archive_to_rejected(character_path: Path, step_key: str, frame: Path) -> Path:
    """Move ``frame`` into ``rejected/`` under a fresh ``<step_key>_attempt<N>``.

    Returns the destination path. No-ops when ``frame`` doesn't exist
    (idempotent: the caller doesn't need to gate on file presence).
    """
    rejected = character_path / REJECTED_DIR
    rejected.mkdir(parents=True, exist_ok=True)
    if not frame.exists():
        return rejected / f"{step_key}_attempt0{frame.suffix}"
    n = next_attempt_number(rejected, step_key)
    destination = rejected / f"{step_key}_attempt{n}{frame.suffix}"
    shutil.move(str(frame), destination)
    return destination
