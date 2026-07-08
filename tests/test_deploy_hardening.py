"""Unit tests for #017 deployment hardening — DB-credential fail-fast.

Covers the pure logic of `require_secure_db_credentials`: the dev opt-out, and
rejection of empty / placeholder DB passwords. Mirrors the #016 fail-fast tests
(`SimpleNamespace` cfg, serving-path function, not a `Settings` validator).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.main import require_secure_db_credentials
from hable_ya.config import Settings


class TestRequireSecureDbCredentials:
    def _cfg(self, url: str, *, allow: bool = False) -> SimpleNamespace:
        return SimpleNamespace(database_url=url, allow_default_db_credentials=allow)

    def test_dev_opt_out_allows_placeholder(self) -> None:
        # allow_default_db_credentials=True bypasses the check entirely.
        require_secure_db_credentials(
            self._cfg("postgresql://hable_ya:hable_ya@db:5432/hable_ya", allow=True)
        )

    def test_placeholder_password_rejected(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            require_secure_db_credentials(
                self._cfg("postgresql://hable_ya:hable_ya@db:5432/hable_ya")
            )
        assert "placeholder" in str(exc.value)

    def test_empty_password_rejected(self) -> None:
        with pytest.raises(RuntimeError) as exc:
            require_secure_db_credentials(
                self._cfg("postgresql://hable_ya@db:5432/hable_ya")
            )
        assert "empty" in str(exc.value)

    def test_real_password_passes(self) -> None:
        require_secure_db_credentials(
            self._cfg("postgresql://appuser:s3cr3t-inject3d@db:5432/hable_ya")
        )

    def test_real_password_equal_to_username_ok(self) -> None:
        # Only the password is inspected; a non-placeholder password passes even
        # if it coincides with a non-default username.
        require_secure_db_credentials(
            self._cfg("postgresql://hable_ya:a-real-strong-password@db:5432/hable_ya")
        )


def test_keyless_settings_still_constructs() -> None:
    # The CI invariant: Settings() builds with no env, and the new flag defaults
    # to the safe (validation-on) value — the check lives on the serving path.
    cfg = Settings()
    assert cfg.allow_default_db_credentials is False
