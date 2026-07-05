"""Structural guard: docker-compose has no on-device GPU scaffolding (spec 009).

Cheap regression check so the llama.cpp service / nvidia GPU reservation can't
silently return to the cloud fork's compose file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

COMPOSE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _compose() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text())


def test_no_llama_service() -> None:
    assert "llama" not in _compose()["services"]


def test_app_has_no_gpu_reservation() -> None:
    app = _compose()["services"]["app"]
    reservations = app.get("deploy", {}).get("resources", {}).get("reservations", {})
    assert "devices" not in reservations


def test_app_does_not_depend_on_llama() -> None:
    app = _compose()["services"]["app"]
    assert "llama" not in (app.get("depends_on") or {})


def test_db_service_present() -> None:
    assert "db" in _compose()["services"]
