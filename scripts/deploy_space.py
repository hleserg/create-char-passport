"""Deploy the Docker frontend (HLE-837, P3) to a Hugging Face Docker Space.

Uploads the Dockerfile, the package source, the ``web/`` SPA, ``pyproject.toml``
and the Docker Space README (as ``README.md``) to a target Space. Defaults to a
**separate** ``-web`` Space so the live Gradio prod Space stays untouched until
the cutover is deliberate.

Usage::

    HF_TOKEN=... uv run python scripts/deploy_space.py [--repo owner/name]

The token is read from ``--token`` or ``$HF_TOKEN``. The target Space is created
(``sdk: docker``) if absent.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "hleserg/create-char-passport-web"
# (local path, path in the Space repo)
FILES: tuple[tuple[str, str], ...] = (
    ("Dockerfile", "Dockerfile"),
    ("pyproject.toml", "pyproject.toml"),
    ("deploy/README.space-docker.md", "README.md"),
)
FOLDERS: tuple[tuple[str, str], ...] = (
    ("src", "src"),
    ("web", "web"),
)


def deploy(repo_id: str, token: str) -> str:
    """Create (if needed) and push the Docker frontend to ``repo_id``; return its URL."""
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    for local, in_repo in FILES:
        api.upload_file(
            path_or_fileobj=str(REPO_ROOT / local),
            path_in_repo=in_repo,
            repo_id=repo_id,
            repo_type="space",
        )
    for local, in_repo in FOLDERS:
        api.upload_folder(
            folder_path=str(REPO_ROOT / local),
            path_in_repo=in_repo,
            repo_id=repo_id,
            repo_type="space",
        )
    return f"https://huggingface.co/spaces/{repo_id}"


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="target Space (owner/name)")
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN", ""), help="HF token")
    args = parser.parse_args()
    if not args.token:
        print("error: no token (pass --token or set HF_TOKEN)", file=sys.stderr)
        return 2
    url = deploy(args.repo, args.token)
    print(f"deployed -> {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
