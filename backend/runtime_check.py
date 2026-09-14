"""ONE-TIME runtime check for the auto-loop verification (delete after)."""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

# Load project .env (presence only — values never printed)
for line in Path(__file__).resolve().parents[1].joinpath(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    seeds = line.strip()
    if seeds and not seeds.startswith("#") and "=" in seeds:
        k, _, v = seeds.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("cryptography importable:", end=" ")
try:
    import cryptography  # noqa: F401
    from alfred.crypto import decrypt_secret, encrypt_secret  # noqa: F401

    print("YES")
except Exception as exc:
    print(f"NO ({exc})")
    sys.exit(1)

from alfred.app import db  # noqa: E402

print("server db is_postgres:", db.is_postgres)
print("ALFRED_ENCRYPTION_KEY present in project env:", bool(os.environ.get("ALFRED_ENCRYPTION_KEY")))
print("ALFRED_REPO_TARGET present:", bool(os.environ.get("ALFRED_REPO_TARGET")))

try:
    import docker  # type: ignore

    docker.client.from_env().ping()
    print("docker (sdk): up")
except Exception:
    try:
        import subprocess

        r = subprocess.run(["docker", "ps"], capture_output=True, timeout=15)
        print("docker (cli):", "up" if r.returncode == 0 else "DOWN")
    except Exception:
        print("docker: DOWN")
