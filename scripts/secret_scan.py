"""Scan tracked files for committed secrets (run before every push).

    python scripts/secret_scan.py          # exit 1 and list findings if anything matches

A small, dependency-free pattern scan over `git ls-files`: cloud keys, private
keys, provider tokens, and credentials embedded in URLs. Test files that hold
deliberately fake secrets (to prove redaction works) are allow-listed by path
and must use obviously fake values. Not a replacement for a dedicated scanner
in CI (see docs/security.md), but it runs anywhere with Python and git.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "AWS access key": re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "OpenAI/Anthropic key": re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{32,}\b"),
    "credential in URL": re.compile(r"\b[a-z][a-z0-9+.-]*://[^:\s/@'\"]+:([^@\s'\"$]{6,})@"),
}
# Values that are placeholders, not secrets (in URLs and examples).
PLACEHOLDERS = re.compile(r"change-me|example|placeholder|opspilot_dev|opspilot_test|\$\{", re.I)
# Tests that contain fake secrets on purpose, to prove they get redacted.
ALLOWED_PATHS = {
    "apps/api/tests/unit/test_rag.py",
    "apps/api/tests/unit/test_security.py",
    "apps/api/tests/unit/test_adapters.py",
    "apps/api/tests/unit/test_config.py",
    "apps/web/tests/unit/redact.test.ts",
    "apps/web/tests/unit/security.test.tsx",
    "scripts/secret_scan.py",
    "tests/security/test_static_security.py",
}
SKIP_SUFFIXES = {".png", ".jpg", ".ico", ".woff", ".woff2", ".lock"}


def tracked_files() -> list[str]:
    # Fixed command, no user input; git is resolved from PATH like any developer tool.
    out = subprocess.run(
        ["git", "ls-files"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def scan(files: list[str]) -> list[str]:
    findings = []
    for rel in files:
        if rel in ALLOWED_PATHS or Path(rel).suffix in SKIP_SUFFIXES:
            continue
        if rel.endswith("package-lock.json"):
            continue  # integrity hashes, not secrets
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for name, pattern in PATTERNS.items():
                match = pattern.search(line)
                if match and not PLACEHOLDERS.search(match.group(0)):
                    findings.append(f"{rel}:{lineno}: possible {name}")
    return findings


def main() -> int:
    files = tracked_files()
    tracked_env = [f for f in files if Path(f).name == ".env"]
    findings = scan(files) + [f"{f}: .env file is tracked" for f in tracked_env]
    for finding in findings:
        sys.stdout.write(finding + "\n")
    sys.stdout.write(f"secret scan: {len(files)} tracked files, {len(findings)} findings\n")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
