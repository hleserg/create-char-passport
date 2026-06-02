"""Filesystem-backed persistence for character state and generated assets.

On Hugging Face Spaces, an HF Storage Bucket mounts at a configurable path
(``APP_BUCKET_PATH``); locally it is just a writable directory. Everything
in this layer is plain ``pathlib`` — :mod:`huggingface_hub` is not needed
for foundation work.
"""

from create_char_passport.storage.bucket import (
    APPROVED_DIR,
    REFS_DIR,
    REJECTED_DIR,
    STATE_FILENAME,
    archive_to_rejected,
    bucket_root,
    character_asset,
    character_dir,
    list_character_ids,
    load_state,
    next_attempt_number,
    save_state,
    save_to_approved,
)

__all__ = [
    "APPROVED_DIR",
    "REFS_DIR",
    "REJECTED_DIR",
    "STATE_FILENAME",
    "archive_to_rejected",
    "bucket_root",
    "character_asset",
    "character_dir",
    "list_character_ids",
    "load_state",
    "next_attempt_number",
    "save_state",
    "save_to_approved",
]
