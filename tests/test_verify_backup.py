import sqlite3

from scripts.verify_backup import main


def test_verify_backup_accepts_valid_sqlite(tmp_path, monkeypatch, capsys):
    backup = tmp_path / "backup.db"
    connection = sqlite3.connect(backup)
    connection.execute("CREATE TABLE leads (id INTEGER PRIMARY KEY)")
    connection.commit()
    connection.close()

    monkeypatch.setattr("sys.argv", ["verify_backup", str(backup)])
    assert main() == 0
    assert "integrity check passed" in capsys.readouterr().out


def test_verify_backup_rejects_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["verify_backup", str(tmp_path / "missing.db")])
    assert main() == 1
