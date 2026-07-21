"""Fail CI if Git tracks runtime secrets, databases, sessions or archives."""

import subprocess
FORBIDDEN_SUFFIXES = (
    ".zip", ".7z", ".rar", ".tar", ".tgz",
    ".session", ".session-journal", ".db", ".sqlite", ".sqlite3",
    ".db-wal", ".db-shm",
)
FORBIDDEN_NAMES = {".env", "chat_monitor_qr.png"}


def main() -> None:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], text=False
    ).decode("utf-8", errors="replace")
    paths = [raw for raw in output.split("\0") if raw]
    forbidden = [
        path for path in paths
        if (
            path.split("/")[-1] in FORBIDDEN_NAMES
            or (path.split("/")[-1].startswith(".env.") and path.split("/")[-1] != ".env.example")
            or path.lower().endswith(FORBIDDEN_SUFFIXES)
        )
    ]
    if forbidden:
        raise SystemExit("Forbidden tracked files:\n" + "\n".join(sorted(forbidden)))
    print("Tracked secret/runtime file check: OK")


if __name__ == "__main__":
    main()
