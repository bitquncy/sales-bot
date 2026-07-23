import pytest

from scripts import check_tracked_secrets, healthcheck


def test_check_tracked_secrets_flags_deleted_tracked_archives(monkeypatch):
    tracked = "project.zip\0README.md\0"

    def fake_output(*_args, **_kwargs):
        return tracked.encode("utf-8")

    monkeypatch.setattr(check_tracked_secrets.subprocess, "check_output", fake_output)

    with pytest.raises(SystemExit, match=r"project\.zip"):
        check_tracked_secrets.main()


def test_mask_db_url_hides_credentials():
    masked = healthcheck._mask_db_url("postgresql+asyncpg://user:secret@example.com:5432/app")
    assert masked == "postgresql+asyncpg://example.com:5432/app"
    assert "secret" not in masked
