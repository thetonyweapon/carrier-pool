"""Validate required production documentation and operator commands."""

import re
from pathlib import Path


def _project_root() -> Path:
    candidates = (Path.cwd(), Path.cwd().parent, Path(__file__).resolve().parents[2])
    for candidate in candidates:
        if (candidate / "PRODUCTION_RUNBOOK.md").is_file():
            return candidate
    return Path(__file__).resolve().parents[2]


ROOT = _project_root()
REQUIRED_FILES = (
    "README.md",
    "DECISIONS.md",
    "PRODUCTION_RUNBOOK.md",
    "openspec/project.md",
    "openspec/specs/platform-hardening/spec.md",
    "openspec/architecture/README.md",
    "openspec/architecture/context.md",
    "openspec/architecture/decisions.md",
    "openspec/architecture/containers.md",
    "openspec/architecture/components.md",
)
REQUIRED_RUNBOOK_TEXT = (
    "validate_resource_limits.py",
    "--env-file",
    "/live",
    "/ready",
    "/metrics",
    "ingestion-worker",
    "replay_ingestion_job",
    "DATABASE_URL",
    "AUTH_ISSUER",
    "dead-letter",
    "source filename",
    "queued checksum",
    'status="dead_letter"',
    "stop backend ingestion-worker frontend",
)
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def validate_documentation() -> None:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).is_file()]
    if missing:
        raise ValueError(f"missing required documentation: {', '.join(missing)}")
    runbook = (ROOT / "PRODUCTION_RUNBOOK.md").read_text()
    absent = [text for text in REQUIRED_RUNBOOK_TEXT if text not in runbook]
    if absent:
        raise ValueError(f"runbook is missing required guidance: {', '.join(absent)}")
    spec = (ROOT / "openspec/specs/platform-hardening/spec.md").read_text()
    if "Milestones 1-11 are delivered" not in spec:
        raise ValueError("platform hardening status is stale")
    project = (ROOT / "openspec/project.md").read_text()
    if "Delivered (milestones 1-11)" not in project:
        raise ValueError("project capability status is stale")
    for relative in REQUIRED_FILES:
        document = ROOT / relative
        for target in MARKDOWN_LINK.findall(document.read_text()):
            target = target.split("#", 1)[0]
            if target and not target.startswith(("http://", "https://")):
                if not (document.parent / target).resolve().is_file():
                    raise ValueError(f"broken documentation link in {relative}: {target}")
    stale_phrases = (
        "rather than a background ingestion service",
        "A scheduler or ingestion API can be added later",
        "production hardening work that remains planned",
        "Property-based tests (Hypothesis)",
        "database-level integration test suite that runs against a real Postgres",
    )
    all_docs = "\n".join((ROOT / relative).read_text() for relative in REQUIRED_FILES)
    for phrase in stale_phrases:
        if phrase in all_docs:
            raise ValueError(f"stale documentation phrase: {phrase}")


if __name__ == "__main__":
    validate_documentation()
    print("production documentation is consistent")
