"""Every repository path named in the orientation docs exists (spec #029).

`OVERVIEW.md` and `ARCHITECTURE.md` are what `README.md` points a new
contributor — or agent — at first, and both had been describing a different
repository since #000: hable-ya's docs, ported as "to be rewritten by #015",
where #015 rewrote only the cloud-posture axis it was scoped to. The component
map still listed `finetune/` four specs after its deletion, and `config.py` was
still credited with `db_path` and `llama_cpp_url`, neither of which exists.

Inspection is what let that happen, so this executes the claim instead. It is
deliberately narrow: it asserts that a named path is not *dangling*, not that
the prose around it is true. That is the class of error which appears the moment
code moves, and it is cheap enough to run on every commit. Broader verification
belongs to review.

The companion to `test_readme_snippets.py` (#022), including its guard against a
docs reshuffle silently turning the suite vacuous.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS = REPO_ROOT / "docs" / "specs"

DOCS = {
    "OVERVIEW.md": SPECS / "OVERVIEW.md",
    "ARCHITECTURE.md": SPECS / "ARCHITECTURE.md",
}

#: Below this, assume the extractor broke rather than that the docs shrank.
#: Set well under the real counts (~40 and ~60) so ordinary editing does not
#: trip it, while a regex that matches nothing still fails loudly.
MIN_PATHS = {"OVERVIEW.md": 10, "ARCHITECTURE.md": 20}

#: Paths that are named deliberately without existing. Each entry must carry a
#: reason, and `test_known_absent_are_actually_absent` deletes the excuse for
#: keeping one past its usefulness: if the path comes back, the test fails and
#: the entry has to go.
KNOWN_ABSENT: dict[str, str] = {
    # Empty by design. Historical references (e.g. `finetune/`, removed in #011)
    # belong in ROADMAP entries and decision records, which this does not check.
}

#: Source extensions that make a bare token a path even without a slash —
#: `render.py` and `Caddyfile` are referenced without a directory.
_EXTENSIONS = (
    ".py",
    ".md",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".css",
    ".sh",
    ".sql",
    ".lock",
)

#: Only backtick-quoted spans are considered. Prose naming a module in passing
#: is not a claim about the filesystem; code formatting is what makes it one.
_CODE_SPAN = re.compile(r"`([^`\n]+)`")

#: Trailing `:12` / `:12-34` line references, and sentence punctuation that ends
#: up inside the span.
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


def _looks_like_path(token: str) -> bool:
    if any(ch in token for ch in " \t()[]{}<>|*$"):
        return False
    if token.startswith(("-", "$")):
        return False
    # A leading slash means an HTTP route (`/ws/session`, `/api/learner`), not a
    # file. A colon means a URL scheme, a DSN, or a Docker image tag
    # (`apache/age:release_PG18_1.7.0`) — line suffixes were stripped already.
    if token.startswith("/") or ":" in token:
        return False
    # `hable_ya/` and `web/src/routes/` are paths; `id = 1` and `count()` are not.
    return "/" in token or token.endswith(_EXTENSIONS)


def _resolve(path: str, doc: Path) -> bool:
    """Repo-relative, or relative to the document — markdown links are both.

    `docs/specs/OVERVIEW.md` links its siblings as `ARCHITECTURE.md` and its
    children as `analiza/spec.md`; both are correct links and neither resolves
    from the repo root.
    """
    return (REPO_ROOT / path).exists() or (doc.parent / path).exists()


def _normalize(token: str) -> str:
    token = token.strip().rstrip(".,;:")
    token = _LINE_SUFFIX.sub("", token)
    return token.rstrip("/")


def extract_paths(text: str) -> set[str]:
    """Repo-relative paths claimed by a document.

    Glob-ish and placeholder spans (`eval/fixtures/*.json`,
    `web/src/**/*.test.ts`, `<category>.json`) are dropped by `_looks_like_path`
    rather than resolved: expanding them would test the shape of the docs'
    wildcards instead of the existence of real files.
    """
    found = set()
    for raw in _CODE_SPAN.findall(text):
        token = _normalize(raw)
        if token and _looks_like_path(token):
            found.add(token)
    return found


@pytest.mark.parametrize("name", sorted(DOCS))
def test_finds_paths_to_check(name: str) -> None:
    # Without this, a reshuffle that breaks extraction would turn every
    # assertion below into a vacuous pass — the failure mode that makes a
    # green suite worse than no suite.
    paths = extract_paths(DOCS[name].read_text())
    assert len(paths) >= MIN_PATHS[name], (
        f"{name}: extracted only {len(paths)} paths "
        f"(expected >= {MIN_PATHS[name]}) — the extractor is probably broken"
    )


@pytest.mark.parametrize("name", sorted(DOCS))
def test_documented_paths_exist(name: str) -> None:
    doc = DOCS[name]
    dangling = sorted(
        path
        for path in extract_paths(doc.read_text())
        if path not in KNOWN_ABSENT and not _resolve(path, doc)
    )
    assert not dangling, (
        f"{name} names {len(dangling)} path(s) that do not exist: "
        f"{', '.join(dangling)}\n"
        "Either the doc is stale, or the path moved. If it is named "
        "deliberately, add it to KNOWN_ABSENT with a reason."
    )


def test_known_absent_are_actually_absent() -> None:
    resurrected = sorted(p for p in KNOWN_ABSENT if (REPO_ROOT / p).exists())
    assert not resurrected, (
        f"KNOWN_ABSENT entries that now exist: {', '.join(resurrected)} — "
        "remove them so the allowlist cannot outlive its reason."
    )
