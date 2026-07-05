"""Download Gemma 4 E4B model in GGUF and/or HuggingFace formats."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = REPO_ROOT / "models"

DEFAULT_HF_REPO = "unsloth/gemma-4-E4B-it"
DEFAULT_GGUF_REPO = "unsloth/gemma-4-E4B-it-GGUF"
DEFAULT_GGUF_FILE = "gemma-4-E4B-it-Q4_K_M.gguf"
LOCAL_GGUF_NAME = "gemma-4-e4b.gguf"  # matches docker-compose.yml


def _get_token() -> str | None:
    """Return HF token from env or cached login."""
    return os.environ.get("HF_TOKEN") or None


def download_gguf(
    repo: str = DEFAULT_GGUF_REPO,
    filename: str = DEFAULT_GGUF_FILE,
    output_dir: Path = MODELS_DIR,
    force: bool = False,
    token: str | None = None,
) -> Path:
    from huggingface_hub import hf_hub_download

    dest = output_dir / LOCAL_GGUF_NAME
    if dest.exists() and not force:
        print(f"GGUF already exists at {dest} (use --force to re-download)")
        return dest

    print(f"Downloading {repo}/{filename} ...")
    downloaded = hf_hub_download(
        repo_id=repo,
        filename=filename,
        token=token,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(downloaded, dest)
    print(f"Saved GGUF → {dest}")
    return dest


def download_hf_weights(
    repo: str = DEFAULT_HF_REPO,
    output_dir: Path = MODELS_DIR,
    force: bool = False,
    token: str | None = None,
) -> Path:
    from huggingface_hub import snapshot_download

    dest = output_dir / "gemma-4-e4b-hf"
    if dest.exists() and not force:
        print(f"HF weights already exist at {dest} (use --force to re-download)")
        return dest

    print(f"Downloading {repo} (full weights) ...")
    snapshot_download(
        repo_id=repo,
        local_dir=str(dest),
        token=token,
    )
    print(f"Saved HF weights → {dest}")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hf-repo",
        default=DEFAULT_HF_REPO,
        help=f"HuggingFace repo for full weights (default: {DEFAULT_HF_REPO})",
    )
    parser.add_argument(
        "--gguf-repo",
        default=DEFAULT_GGUF_REPO,
        help=f"HuggingFace repo for GGUF (default: {DEFAULT_GGUF_REPO})",
    )
    parser.add_argument(
        "--gguf-file",
        default=DEFAULT_GGUF_FILE,
        help=f"GGUF filename to download (default: {DEFAULT_GGUF_FILE})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=MODELS_DIR,
        help=f"Output directory (default: {MODELS_DIR})",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--gguf-only",
        action="store_true",
        help="Download only the GGUF quantized model",
    )
    group.add_argument(
        "--hf-only",
        action="store_true",
        help="Download only the full HuggingFace weights",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if files already exist",
    )
    args = parser.parse_args()

    token = _get_token()
    if token is None:
        print(
            "Warning: No HF_TOKEN found. Gemma models are gated — if the "
            "download fails, set HF_TOKEN or run: huggingface-cli login",
            file=sys.stderr,
        )

    try:
        if not args.hf_only:
            download_gguf(
                repo=args.gguf_repo,
                filename=args.gguf_file,
                output_dir=args.output_dir,
                force=args.force,
                token=token,
            )
        if not args.gguf_only:
            download_hf_weights(
                repo=args.hf_repo,
                output_dir=args.output_dir,
                force=args.force,
                token=token,
            )
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        if token is None:
            print(
                "Hint: Set HF_TOKEN or run `huggingface-cli login` for gated models.",
                file=sys.stderr,
            )
        return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
