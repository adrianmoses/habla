"""CLI orchestration tests (spec §1): output destination resolution.

The vault is one destination among several, not a prerequisite — a run with
nothing configured still has somewhere to write.
"""

from pathlib import Path

from analiza import note
from analiza.cli import _resolve_base
from analiza.config import Config


def test_nothing_configured_defaults_into_the_repo() -> None:
    """No vault, no --out, no config: writes flat to the default dir."""
    assert _resolve_base(None, None, Config()) == note.DEFAULT_OUTPUT_DIR
    assert "Español" not in str(note.DEFAULT_OUTPUT_DIR)


def test_out_flag_writes_flat() -> None:
    assert _resolve_base(None, Path("/o"), Config()) == Path("/o")


def test_config_output_dir_used_when_no_flag() -> None:
    cfg = Config(output_dir=Path("/cfg-out"))
    assert _resolve_base(None, None, cfg) == Path("/cfg-out")


def test_out_flag_overrides_config_output_dir() -> None:
    cfg = Config(output_dir=Path("/cfg-out"))
    assert _resolve_base(None, Path("/flag"), cfg) == Path("/flag")


def test_vault_flag_selects_nested_layout() -> None:
    assert _resolve_base(Path("/v"), None, Config()) == Path("/v/Español")


def test_config_vault_path_selects_nested_layout() -> None:
    cfg = Config(vault_path=Path("/cfg-vault"))
    assert _resolve_base(None, None, cfg) == Path("/cfg-vault/Español")


def test_vault_wins_over_out() -> None:
    """--vault is the more specific intent: it also picks the layout."""
    assert _resolve_base(Path("/v"), Path("/o"), Config()) == Path("/v/Español")


def test_vault_flag_overrides_config_vault_path() -> None:
    cfg = Config(vault_path=Path("/cfg-vault"))
    assert _resolve_base(Path("/flag"), None, cfg) == Path("/flag/Español")


def test_config_vault_wins_over_out_flag() -> None:
    """A configured vault still selects the vault layout — --out does not
    silently downgrade it to flat, it is simply lower precedence."""
    cfg = Config(vault_path=Path("/cfg-vault"))
    assert _resolve_base(None, Path("/o"), cfg) == Path("/cfg-vault/Español")
