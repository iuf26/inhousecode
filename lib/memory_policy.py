#!/usr/bin/env python3
"""OpenViking-only governed memory for inhousecode reviews.

OpenViking is the sole persistent store. This module never creates repository
memory files. It owns record validation, candidate lifecycle, promotion policy,
retrieval filtering, review snapshots, and the command-line bridge used by the
Bash orchestrator.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT_URI = "viking://resources/inhousecode/memory-policy"
SCHEMA_URI = ROOT_URI + "/_schema/"
GLOBAL_URI = ROOT_URI + "/global/"
PROJECTS_URI = ROOT_URI + "/projects/"
CANDIDATE_URI = ROOT_URI + "/candidate_memory/"
INBOX_URI = CANDIDATE_URI + "inbox/"
CLASSIFIED_URI = CANDIDATE_URI + "classified/"
QUARANTINE_URI = CANDIDATE_URI + "quarantine/"

PROJECT_LIMIT = 8
PROJECT_THRESHOLD = 0.65
GLOBAL_LIMIT = 5
GLOBAL_THRESHOLD = 0.70
CANDIDATE_LIMIT = 3
CANDIDATE_THRESHOLD = 0.75
CANDIDATE_SCOPE_SCAN_LIMIT = 50
DEFAULT_CONTEXT_MAX_CHARS = 4000
PATH_REVIEW_QUERY_MAX_CHARS = 4000

REQUIRED_FIELDS = (
    "id",
    "memory_type",
    "repository_id",
    "status",
    "source",
    "created_at",
    "last_verified_at",
    "review_after",
    "expires_at",
    "confidence",
    "evidence",
    "promotion_mode",
    "promotion_reason",
    "promoted_to",
    "promoted_at",
    "content",
)
VALID_MEMORY_TYPES = {"global", "project", "candidate"}
VALID_STATUSES = {
    "candidate",
    "classified",
    "promoted",
    "rejected",
    "expired",
    "superseded",
    "quarantined",
}
VALID_CONFIDENCE = {"low", "medium", "high"}
INACTIVE_STATUSES = {"rejected", "expired", "superseded", "quarantined"}

# --- review sessions and harvest ---------------------------------------------
# Review outcomes are written as OpenViking sessions under a dedicated user so
# OpenViking's extractor learns from them without touching anyone's personal
# memories. The harvest reads what it extracted back as *candidates* only.
SESSION_USER_PREFIX = "inhousecode-"
SESSION_USER_ENV = "INHOUSECODE_OV_SESSION_USER"
SESSION_USER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
RESERVED_SESSION_USERS = {"default", "admin", "root"}
SESSION_ID_PREFIX = "ihc-"
SESSION_SOURCE_TAG = "inhousecode"
SESSION_MAX_CHARS = 6000
SESSION_MAX_FINDINGS = 25
HARVEST_SOURCE = "openviking-session"
HARVEST_DEFAULT_LOOKBACK_DAYS = 7
HARVEST_MAX_ITEM_CHARS = 500
HARVEST_MIN_ITEM_CHARS = 12
# Extracted categories that describe how to do the work. User categories
# (profile, preferences, entities, events) describe people and are never
# harvested into shared review policy.
HARVEST_CATEGORIES = {"cases", "patterns", "tools", "skills"}
INJECTION_PATTERNS = (
    re.compile(r"ignore (all |any )?(previous|prior|above) (instructions|rules)", re.I),
    re.compile(r"disregard (the |all )?(system|previous|above)", re.I),
    re.compile(r"\b(always|automatically) (approve|pass)\b", re.I),
    re.compile(r"\bapprove every\b", re.I),
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"\byou are now\b", re.I),
)
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]|\x1b\[[0-9;]*[A-Za-z]")
FINDING_MARKERS = ("##CR-FINDING##", "##STATIC-FINDING##")

# --- automatic promotion from recurrence ---------------------------------------
# A harvested lesson is promoted without a human only when separate reviews keep
# producing it. Each review counts once, and only if it fixed something real in
# this repository and was not overridden: learning must never turn "people
# dismissed this finding" into "stop reporting it".
AUTO_PROMOTE_DEFAULT_REVIEWS = 3
AUTO_PROMOTE_MIN_REVIEWS = 2
REVIEW_SESSIONS_DIR = "evidence/_review_sessions/"
MAX_RECORDED_RESOLVED = 50
# Security knowledge always goes to a human, whatever the evidence.
SECURITY_TERMS = re.compile(
    r"\b(secur\w*|auth\w*|password\w*|passwd|secret\w*|credential\w*|token\w*|"
    r"api[ _-]?keys?|crypt\w*|cipher\w*|hash\w*|tls|ssl|cert\w*|x509|cve|"
    r"vuln\w*|exploit\w*|inject\w*|xss|csrf|ssrf|sqli|sql-injection|permission\w*|"
    r"privilege\w*|access[ _-]control|session[ _-]fixation|pii|gdpr|sanitiz\w*|"
    r"escap\w*|deserializ\w*|rce|eval|exec|shell)\b",
    re.I,
)
# Lessons that tell the reviewer to report less change review behavior, which
# needs a human; recurrence alone must not be able to switch a check off.
SUPPRESSION_TERMS = re.compile(
    r"\b(do not|don't|dont|never|stop|no need to|not necessary to|skip|ignore|suppress|"
    r"allow\w*|accept\w*|fine to|ok to|okay to|is acceptable|are acceptable|exempt\w*|"
    r"false positive\w*|tolerat\w*|waive\w*)\b",
    re.I,
)
# Words too common to make two lessons "about the same thing".
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "in", "into", "is", "it", "its", "must", "not", "of", "on", "or", "should",
    "that", "the", "their", "this", "to", "use", "used", "uses", "using", "via",
    "when", "with", "without", "all", "any", "every", "each", "code", "always",
}
CONFLICT_MIN_SHARED_WORDS = 2

SCHEMA_README = """# Inhousecode memory record schema

Every JSON record contains the fields documented by inhousecode: stable ID,
memory type, repository scope, lifecycle status, provenance, verification and
expiry dates, confidence, evidence, promotion metadata, and content.
"""
GLOBAL_README = """# Global knowledge

Human-approved cross-repository facts and team practices. Global promotion
always requires human review.
"""
PROJECTS_README = """# Project knowledge

Promoted knowledge scoped to one canonical repository ID. Safe, well-evidenced
repository facts may be promoted automatically by deterministic policy.
"""
INBOX_README = """# Candidate inbox

New developer feedback and captured review signals. Human authorship records
provenance but does not make a candidate authoritative.
"""
CLASSIFIED_README = """# Classified candidates

Candidates classified for scope, confidence, evidence, risk, and promotion.
They remain unverified evidence unless a promoted record is created.
"""
QUARANTINE_README = """# Candidate quarantine

Unrelated, unsafe, or prompt-injection-like candidates. Quarantined content is
never supplied to reviewers.
"""

STRUCTURAL_RESOURCES = {
    SCHEMA_URI + "README.md": SCHEMA_README,
    GLOBAL_URI + "README.md": GLOBAL_README,
    PROJECTS_URI + "README.md": PROJECTS_README,
    INBOX_URI + "README.md": INBOX_README,
    CLASSIFIED_URI + "README.md": CLASSIFIED_README,
    QUARANTINE_URI + "README.md": QUARANTINE_README,
}
STRUCTURAL_DIRECTORIES = (
    ROOT_URI,
    SCHEMA_URI.rstrip("/"),
    GLOBAL_URI.rstrip("/"),
    PROJECTS_URI.rstrip("/"),
    CANDIDATE_URI.rstrip("/"),
    INBOX_URI.rstrip("/"),
    CLASSIFIED_URI.rstrip("/"),
    QUARANTINE_URI.rstrip("/"),
)


class OpenVikingError(RuntimeError):
    """OpenViking is missing, unavailable, or returned invalid data."""


class NotFound(OpenVikingError):
    """An exact OpenViking URI does not exist."""


class AlreadyExists(OpenVikingError):
    """A strict OpenViking create targeted an existing URI."""


class RecordError(ValueError):
    """A memory record violates the inhousecode schema."""


def encode_repository_id(repository_id: str) -> str:
    if not repository_id.strip():
        raise ValueError("repository_id cannot be empty")
    encoded = base64.urlsafe_b64encode(repository_id.encode("utf-8")).decode("ascii")
    return "repo_" + encoded.rstrip("=")


def decode_repository_id(segment: str) -> str:
    if not segment.startswith("repo_"):
        raise ValueError("encoded repository ID must start with repo_")
    encoded = segment[5:]
    encoded += "=" * (-len(encoded) % 4)
    return base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")


def normalize_remote(remote: str) -> str:
    value = remote.strip()
    if not value:
        return ""
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
        value = f"{host}/{path}"
    else:
        value = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", value)
        value = re.sub(r"^[^@/]+@", "", value)
    return value.removesuffix(".git").strip("/").lower()


def repository_id_for(repo_root: Path) -> str:
    configured = os.environ.get("INHOUSECODE_REPOSITORY_ID", "").strip()
    if configured:
        return configured
    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    remote = normalize_remote(result.stdout) if result.returncode == 0 else ""
    if remote:
        return remote
    digest = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"local/{repo_root.name}-{digest}"


def new_record(
    *,
    record_id: str,
    memory_type: str,
    repository_id: str | None,
    status: str,
    source: str,
    created_at: str,
    confidence: str,
    evidence: list[str],
    content: str,
    last_verified_at: str | None = None,
    review_after: str | None = None,
    expires_at: str | None = None,
    promotion_mode: str | None = None,
    promotion_reason: str | None = None,
    promoted_to: str | None = None,
    promoted_at: str | None = None,
) -> dict:
    record = {
        "id": record_id,
        "memory_type": memory_type,
        "repository_id": repository_id,
        "status": status,
        "source": source,
        "created_at": created_at,
        "last_verified_at": last_verified_at,
        "review_after": review_after,
        "expires_at": expires_at,
        "confidence": confidence,
        "evidence": list(evidence),
        "promotion_mode": promotion_mode,
        "promotion_reason": promotion_reason,
        "promoted_to": promoted_to,
        "promoted_at": promoted_at,
        "content": content.strip(),
    }
    validate_record(record)
    return record


def validate_record(record: dict) -> None:
    missing = [field for field in REQUIRED_FIELDS if field not in record]
    if missing:
        raise RecordError("missing record fields: " + ", ".join(missing))
    if record["memory_type"] not in VALID_MEMORY_TYPES:
        raise RecordError(f"invalid memory_type: {record['memory_type']!r}")
    if record["status"] not in VALID_STATUSES:
        raise RecordError(f"invalid status: {record['status']!r}")
    if record["confidence"] not in VALID_CONFIDENCE:
        raise RecordError(f"invalid confidence: {record['confidence']!r}")
    if not isinstance(record["evidence"], list):
        raise RecordError("evidence must be an array")
    if not str(record["id"]).strip() or not str(record["content"]).strip():
        raise RecordError("id and content cannot be empty")
    if record["memory_type"] == "project" and not record["repository_id"]:
        raise RecordError("project memory requires repository_id")
    if record["promotion_mode"] not in (None, "automatic", "human"):
        raise RecordError("promotion_mode must be automatic, human, or null")
    for field in ("created_at", "last_verified_at", "review_after", "expires_at", "promoted_at"):
        value = record[field]
        if value is not None:
            try:
                date.fromisoformat(value)
            except (TypeError, ValueError) as error:
                raise RecordError(f"{field} must be an ISO date or null") from error


def serialize_record(record: dict) -> str:
    validate_record(record)
    return json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _check_dates(expires_at: str | None, review_after: str | None) -> None:
    for name, value in (("expires_at", expires_at), ("review_after", review_after)):
        if value is None:
            continue
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise RecordError(f"{name} must be an ISO date (YYYY-MM-DD), got {value!r}") from error


def parse_record(content: str) -> dict:
    try:
        record = json.loads(content)
    except json.JSONDecodeError as error:
        raise RecordError(f"invalid record JSON: {error}") from error
    if not isinstance(record, dict):
        raise RecordError("record must be a JSON object")
    validate_record(record)
    return record


def parse_time_range(prompt: str, today: date) -> tuple[str | None, str | None]:
    normalized = prompt.lower()
    if "last week" in normalized or "past week" in normalized:
        return (today - timedelta(days=7)).isoformat(), today.isoformat()
    match = re.search(r"(?:last|past)\s+(\d+)\s+days?", normalized)
    if match:
        days = int(match.group(1))
        return (today - timedelta(days=days)).isoformat(), today.isoformat()
    if "today" in normalized:
        value = today.isoformat()
        return value, value
    return None, None


def parse_legacy_markdown(content: str) -> tuple[dict[str, str], str] | None:
    """Read the small front-matter shape used by the removed local policy."""
    if not content.startswith("---\n"):
        return None
    parts = content.split("---", 2)
    if len(parts) != 3:
        return None
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    body = parts[2].strip()
    return (metadata, body) if body else None


def migrate_legacy_namespace(
    client: "OpenVikingClient",
    policy: "MemoryPolicy",
    source_root: str,
) -> list[dict]:
    """Copy legacy policy records into candidates without deleting any source."""
    client.health()
    migrated = []
    prefix = source_root.rstrip("/") + "/"
    for item in client.tree(source_root):
        uri = str(item.get("uri", ""))
        if not uri.startswith(prefix) or item.get("isDir"):
            continue
        if uri.endswith(("README.md", ".abstract.md", ".overview.md")) or "/_schema/" in uri:
            continue
        parsed = parse_legacy_markdown(client.read(uri))
        if not parsed:
            continue
        metadata, body = parsed
        digest = hashlib.sha256(uri.encode("utf-8")).hexdigest()[:20]
        record_id = "candidate-migrated-" + digest
        old_status = metadata.get("status", "candidate")
        status = "candidate" if old_status == "candidate" else "classified"
        repository_id = None
        project_match = re.search(r"/projects/([^/]+)/", uri)
        if project_match:
            repository_id = "legacy/" + project_match.group(1)
        record = new_record(
            record_id=record_id,
            memory_type="candidate",
            repository_id=repository_id,
            status=status,
            source="migration:" + metadata.get("source", "unknown"),
            created_at=metadata.get("created_at", policy.today().isoformat()),
            confidence="medium",
            evidence=[uri],
            promotion_reason="migrated from legacy namespace; scope requires human review",
            content=body,
        )
        destination_root = INBOX_URI if status == "candidate" else CLASSIFIED_URI
        destination = destination_root + record_id + ".json"
        client.write(destination, serialize_record(record))
        migrated.append({"source_uri": uri, "destination_uri": destination})
    return migrated


class OpenVikingClient:
    """Small subprocess adapter for the OpenViking CLI."""

    def __init__(self, binary: str | None = None, env: dict[str, str] | None = None):
        self.binary = binary or os.environ.get("OV_BIN") or shutil.which("ov") or ""
        if not self.binary:
            raise OpenVikingError("OpenViking CLI 'ov' is not installed or not on PATH")
        self.env = os.environ.copy()
        if env:
            self.env.update(env)
        if "OPENVIKING_CLI_CONFIG_FILE" not in self.env:
            local_config = Path.home() / ".openviking" / "ovcli.conf.local"
            if local_config.is_file():
                self.env["OPENVIKING_CLI_CONFIG_FILE"] = str(local_config)

    def _run(self, arguments: list[str]) -> object:
        result = subprocess.run(
            [self.binary, "-o", "json", *arguments],
            text=True,
            capture_output=True,
            env=self.env,
            check=False,
        )
        payload = None
        output = result.stdout.strip()
        for stream in (result.stdout, result.stderr):
            candidate = stream.strip()
            if not candidate or "{" not in candidate:
                continue
            try:
                decoded = json.loads(candidate[candidate.find("{") :])
                if isinstance(decoded, dict):
                    payload = decoded
                    break
            except (ValueError, json.JSONDecodeError):
                continue
        if result.returncode != 0 or not isinstance(payload, dict) or not payload.get("ok"):
            error = payload.get("error", {}) if isinstance(payload, dict) else {}
            code = str(error.get("code", ""))
            message = str(error.get("message") or result.stderr.strip() or output or "OpenViking command failed")
            if code == "NOT_FOUND":
                raise NotFound(message)
            if code == "ALREADY_EXISTS":
                raise AlreadyExists(message)
            raise OpenVikingError(message)
        return payload.get("result")

    def health(self) -> None:
        result = self._run(["health"])
        if not isinstance(result, dict) or not result.get("healthy"):
            raise OpenVikingError("OpenViking health check did not report healthy")

    def mkdir(self, uri: str) -> None:
        try:
            self._run(["stat", uri])
            return
        except NotFound:
            pass
        try:
            self._run(["mkdir", uri])
        except AlreadyExists:
            return

    def write(self, uri: str, content: str, *, create: bool = False) -> None:
        mode = "create" if create else "replace"
        self._run(
            [
                "write",
                uri,
                "--content",
                content,
                "--mode",
                mode,
                "--wait",
                "--timeout",
                "600",
                "--processing-mode",
                "vectors_only",
            ]
        )
        if self.read(uri) != content:
            raise OpenVikingError(f"OpenViking read-back mismatch for {uri}")

    def read(self, uri: str) -> str:
        result = self._run(["read", uri])
        if not isinstance(result, str):
            raise OpenVikingError(f"OpenViking returned non-text content for {uri}")
        return result

    def find(
        self,
        query: str,
        target_uri: str,
        *,
        limit: int,
        threshold: float,
        after: str | None = None,
        before: str | None = None,
    ) -> list[dict]:
        arguments = [
            "find",
            query,
            "--uri",
            target_uri,
            "--limit",
            str(limit),
            "--threshold",
            str(threshold),
            "--level",
            "2",
        ]
        if after:
            arguments.extend(["--after", after])
        if before:
            arguments.extend(["--before", before])
        result = self._run(arguments)
        if not isinstance(result, dict):
            raise OpenVikingError("OpenViking find returned malformed output")
        resources = result.get("resources", [])
        if not isinstance(resources, list):
            raise OpenVikingError("OpenViking find resources must be an array")
        return resources

    def tree(self, uri: str) -> list[dict]:
        result = self._run(["tree", uri, "--all", "--level-limit", "8", "--node-limit", "10000"])
        if not isinstance(result, list):
            raise OpenVikingError("OpenViking tree returned malformed output")
        return result


class MemoryPolicy:
    def __init__(
        self,
        client: OpenVikingClient,
        repository_id: str,
        *,
        today: Callable[[], date] = date.today,
    ):
        if not repository_id.strip():
            raise ValueError("repository_id cannot be empty")
        self.client = client
        self.repository_id = repository_id
        self.repository_segment = encode_repository_id(repository_id)
        self.today = today

    @property
    def project_base_uri(self) -> str:
        return PROJECTS_URI + self.repository_segment + "/"

    def project_uri(self, filename: str) -> str:
        return self.project_base_uri + filename

    def review_evidence_uri(self, review_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", review_id).strip("-") or "review"
        return self.project_base_uri + "_review_evidence/" + safe + ".json"

    def initialize(self) -> None:
        self.client.health()
        for uri in STRUCTURAL_DIRECTORIES:
            self.client.mkdir(uri)
        for uri, content in STRUCTURAL_RESOURCES.items():
            self.client.write(uri, content)

    def add_candidate(
        self,
        text: str,
        *,
        source: str = "developer",
        evidence: list[str] | None = None,
        repo_root: Path | None = None,
    ) -> tuple[dict, str]:
        del repo_root  # Explicitly accepted to prove no repository memory is written.
        self.client.health()
        clean = text.strip()
        if not clean:
            raise RecordError("candidate content cannot be empty")
        digest = hashlib.sha256(
            f"{self.repository_id}\0{source}\0{clean}".encode("utf-8")
        ).hexdigest()[:20]
        record_id = "candidate-" + digest
        # Human authorship is provenance, not proof: an instruction-like
        # candidate is quarantined no matter who wrote it.
        quarantined = looks_like_injection(clean)
        record = new_record(
            record_id=record_id,
            memory_type="candidate",
            repository_id=self.repository_id,
            status="quarantined" if quarantined else "candidate",
            source=source,
            created_at=self.today().isoformat(),
            confidence="low" if quarantined else "medium",
            evidence=[item.strip() for item in (evidence or []) if item.strip()],
            content=clean,
        )
        uri = (QUARANTINE_URI if quarantined else INBOX_URI) + record_id + ".json"
        self.client.write(uri, serialize_record(record))
        return record, uri

    def _candidate_inbox_uri(self, candidate_id: str) -> str:
        return INBOX_URI + candidate_id + ".json"

    def _candidate_classified_uri(self, candidate_id: str) -> str:
        return CLASSIFIED_URI + candidate_id + ".json"

    def classify_candidate(
        self,
        candidate_id: str,
        *,
        target: str,
        confidence: str,
        evidence: list[str],
        scope_clear: bool = True,
        conflict: bool = False,
        security_sensitive: bool = False,
        affects_review_behavior: bool = False,
        cross_repository: bool = False,
        expires_at: str | None = None,
        review_after: str | None = None,
    ) -> dict:
        self.client.health()
        if target not in ("project", "global"):
            raise RecordError("classification target must be project or global")
        _check_dates(expires_at, review_after)
        inbox_uri = self._candidate_inbox_uri(candidate_id)
        source = parse_record(self.client.read(inbox_uri))
        classified = dict(source)
        classified.update(
            {
                "status": "classified",
                "confidence": confidence,
                "evidence": list(evidence),
                "expires_at": expires_at,
                "review_after": review_after,
                "promotion_mode": None,
                "promotion_reason": None,
                "promoted_to": None,
                "promoted_at": None,
            }
        )
        reasons = []
        if target == "global" or cross_repository:
            reasons.append("global or cross-repository knowledge requires human review")
        if security_sensitive:
            reasons.append("security-sensitive knowledge requires human review")
        if affects_review_behavior:
            reasons.append("review behavior changes require human review")
        if not scope_clear:
            reasons.append("uncertain repository scope requires human review")
        if conflict:
            reasons.append("conflicting knowledge requires human review")
        if confidence != "high":
            reasons.append("high classification confidence is required")
        if not evidence:
            reasons.append("repository evidence is required")
        classified_uri = self._candidate_classified_uri(candidate_id)
        promoted_uri = None
        if reasons:
            classified["promotion_reason"] = "; ".join(reasons)
            self.client.write(classified_uri, serialize_record(classified))
        else:
            promoted = new_record(
                record_id="project-" + candidate_id.removeprefix("candidate-"),
                memory_type="project",
                repository_id=self.repository_id,
                status="promoted",
                source=source["source"],
                created_at=self.today().isoformat(),
                last_verified_at=self.today().isoformat(),
                confidence=confidence,
                evidence=list(evidence) + [inbox_uri],
                expires_at=expires_at,
                review_after=review_after,
                promotion_mode="automatic",
                promotion_reason="safe repository-local fact met automatic promotion policy",
                promoted_at=self.today().isoformat(),
                content=source["content"],
            )
            promoted_uri = self.project_uri(promoted["id"] + ".json")
            self.client.write(promoted_uri, serialize_record(promoted))
            classified.update(
                {
                    "status": "promoted",
                    "promotion_mode": "automatic",
                    "promotion_reason": promoted["promotion_reason"],
                    "promoted_to": promoted_uri,
                    "promoted_at": self.today().isoformat(),
                }
            )
            self.client.write(classified_uri, serialize_record(classified))
        return {
            "classification": classified,
            "classified_uri": classified_uri,
            "inbox_uri": inbox_uri,
            "promoted_uri": promoted_uri,
        }

    def promote_candidate(
        self,
        candidate_id: str,
        *,
        target: str,
        reason: str,
        evidence: list[str],
        expires_at: str | None = None,
        review_after: str | None = None,
    ) -> dict:
        self.client.health()
        if target not in ("project", "global"):
            raise RecordError("promotion target must be project or global")
        _check_dates(expires_at, review_after)
        classified_uri = self._candidate_classified_uri(candidate_id)
        candidate = parse_record(self.client.read(classified_uri))
        memory_type = target
        record_id = target + "-" + candidate_id.removeprefix("candidate-")
        promoted = new_record(
            record_id=record_id,
            memory_type=memory_type,
            repository_id=self.repository_id if target == "project" else None,
            status="promoted",
            source=candidate["source"],
            created_at=self.today().isoformat(),
            last_verified_at=self.today().isoformat(),
            confidence=candidate["confidence"],
            evidence=list(dict.fromkeys(candidate["evidence"] + evidence + [classified_uri])),
            # Explicit dates win; otherwise keep what classification recorded.
            expires_at=expires_at or candidate["expires_at"],
            review_after=review_after or candidate["review_after"],
            promotion_mode="human",
            promotion_reason=reason,
            promoted_at=self.today().isoformat(),
            content=candidate["content"],
        )
        destination = (
            self.project_uri(record_id + ".json")
            if target == "project"
            else GLOBAL_URI + record_id + ".json"
        )
        self.client.write(destination, serialize_record(promoted))
        candidate.update(
            {
                "status": "promoted",
                "promotion_mode": "human",
                "promotion_reason": reason,
                "promoted_to": destination,
                "promoted_at": self.today().isoformat(),
            }
        )
        self.client.write(classified_uri, serialize_record(candidate))
        return {"record": promoted, "uri": destination, "candidate_uri": classified_uri}

    def _read_result(self, result: dict) -> tuple[str, float, dict] | None:
        uri = str(result.get("uri", ""))
        if not uri or uri.endswith("README.md"):
            return None
        content = result.get("content") or result.get("text")
        if not isinstance(content, str):
            try:
                content = self.client.read(uri)
            except NotFound:
                # OpenViking's semantic index can briefly retain a URI after
                # its file is removed. A stale hit is absent evidence, not an
                # unavailable memory service and never active policy.
                return None
        try:
            record = parse_record(content)
        except RecordError:
            return None
        return uri, float(result.get("score", 0.0)), record

    def _search(
        self,
        query: str,
        uri: str,
        *,
        limit: int,
        threshold: float,
        after: str | None = None,
        before: str | None = None,
        include_scoped_tree: bool = False,
    ) -> list[tuple[str, float, dict]]:
        loaded = []
        semantic_failed = False
        try:
            results = self.client.find(
                query,
                uri,
                limit=limit,
                threshold=threshold,
                after=after,
                before=before,
            )
        except NotFound:
            # A deleted resource may remain in OpenViking's semantic index for
            # a short time and make the whole find call fail. Fall back to the
            # governed scope's current tree so active policy is not omitted.
            results = []
            semantic_failed = True

        if semantic_failed or include_scoped_tree:
            seen = {str(result.get("uri") or "") for result in results}
            try:
                nodes = self.client.tree(uri.rstrip("/"))
            except NotFound:
                nodes = []
            for node in nodes:
                resource_uri = str(node.get("uri") or "")
                if (
                    not resource_uri
                    or bool(node.get("isDir") or node.get("is_dir"))
                    or node.get("type") == "directory"
                    or resource_uri in seen
                    or resource_uri.endswith("README.md")
                ):
                    continue
                try:
                    content = self.client.read(resource_uri)
                except NotFound:
                    continue
                results.append(
                    {
                        "uri": resource_uri,
                        "score": 1.0 if semantic_failed else 0.0,
                        "content": content,
                    }
                )
        for result in results:
            parsed = self._read_result(result)
            if parsed:
                loaded.append(parsed)
        return loaded[:limit]

    def _evaluate(
        self,
        items: list[tuple[str, float, dict]],
        *,
        memory_type: str,
    ) -> tuple[list[tuple[str, float, dict, bool]], list[str], list[str]]:
        active = []
        expired = []
        needs_review = []
        today = self.today()
        for uri, score, record in items:
            if record["memory_type"] != memory_type:
                continue
            if memory_type == "project" and record["repository_id"] != self.repository_id:
                continue
            if memory_type == "candidate" and record["repository_id"] not in (None, self.repository_id):
                continue
            if record["status"] in INACTIVE_STATUSES:
                continue
            if memory_type in ("project", "global") and record["status"] != "promoted":
                continue
            if memory_type == "candidate" and record["status"] not in ("candidate", "classified"):
                continue
            expires = record["expires_at"]
            if expires and date.fromisoformat(expires) < today:
                expired.append(uri)
                if record["status"] != "expired":
                    record["status"] = "expired"
                    self.client.write(uri, serialize_record(record))
                continue
            review_after = record["review_after"]
            revalidate = bool(review_after and date.fromisoformat(review_after) < today)
            if revalidate:
                needs_review.append(uri)
                score -= 0.05
            active.append((uri, score, record, revalidate))
        active.sort(key=lambda item: (-item[1], item[0]))
        return active, sorted(expired), sorted(needs_review)

    @staticmethod
    def _render_record(uri: str, record: dict, *, revalidate: bool = False) -> str:
        verification = " — needs verification" if revalidate else ""
        return (
            f"- [{record['id']}] {record['content']}\n"
            f"  URI: {uri}; status: {record['status']}; repository: "
            f"{record['repository_id'] or 'global'}; confidence: {record['confidence']}"
            f"{verification}"
        )

    def _bounded_context(
        self,
        project: list[tuple[str, float, dict, bool]],
        global_records: list[tuple[str, float, dict, bool]],
        candidates: list[tuple[str, float, dict, bool]],
        max_chars: int,
    ) -> tuple[str, list[str], list[str], list[str], list[dict]]:
        sections = []
        selected_project: list[str] = []
        selected_global: list[str] = []
        selected_candidates: list[str] = []
        matches = []
        used = 0
        groups = (
            ("Promoted project knowledge", project, selected_project),
            ("Promoted global knowledge", global_records, selected_global),
            ("Unverified candidate evidence", candidates, selected_candidates),
        )
        for title, records, selected in groups:
            rendered_records = []
            for uri, score, record, revalidate in records:
                block = self._render_record(uri, record, revalidate=revalidate)
                extra = len(block) + (len(title) + 5 if not rendered_records else 1)
                if used + extra > max_chars:
                    continue
                rendered_records.append(block)
                selected.append(uri)
                matches.append({"uri": uri, "score": score, "memory_type": record["memory_type"]})
                used += extra
            if rendered_records:
                sections.append(f"## {title}\n" + "\n".join(rendered_records))
        return "\n\n".join(sections), selected_project, selected_global, selected_candidates, matches

    def build_context(
        self,
        *,
        query: str,
        review_id: str = "review",
        max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    ) -> dict:
        self.client.health()
        project_raw = self._search(
            query,
            self.project_base_uri,
            limit=PROJECT_LIMIT,
            threshold=PROJECT_THRESHOLD,
            include_scoped_tree=True,
        )
        global_raw = self._search(
            query,
            GLOBAL_URI,
            limit=GLOBAL_LIMIT,
            threshold=GLOBAL_THRESHOLD,
        )
        candidate_raw = self._search(
            query,
            CLASSIFIED_URI,
            limit=CANDIDATE_LIMIT,
            threshold=CANDIDATE_THRESHOLD,
        )
        project, project_expired, project_review = self._evaluate(project_raw, memory_type="project")
        global_records, global_expired, global_review = self._evaluate(global_raw, memory_type="global")
        candidates, candidate_expired, candidate_review = self._evaluate(candidate_raw, memory_type="candidate")
        prompt, project_uris, global_uris, candidate_uris, matches = self._bounded_context(
            project, global_records, candidates, max_chars
        )
        snapshot = {
            "review_id": review_id,
            "repository_id": self.repository_id,
            "as_of": self.today().isoformat(),
            "approved_project_records": project_uris,
            "approved_global_records": global_uris,
            "candidate_records": candidate_uris,
            "expired_records_excluded": sorted(project_expired + global_expired + candidate_expired),
            "records_needing_review": sorted(project_review + global_review + candidate_review),
            "matches": matches,
            "prompt_context": prompt,
        }
        canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        snapshot["snapshot_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        evidence = {
            "review_id": review_id,
            "repository_id": self.repository_id,
            "as_of": snapshot["as_of"],
            "consumed_uris": project_uris + global_uris + candidate_uris,
            "matches": matches,
            "snapshot_hash": snapshot["snapshot_hash"],
        }
        self.client.write(
            self.review_evidence_uri(review_id),
            json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        )
        return snapshot

    def view(self, prompt: str) -> str:
        self.client.health()
        after, before = parse_time_range(prompt, self.today())
        show_all = prompt.casefold().startswith("show all ")
        searches = (
            ("Promoted project knowledge", (self.project_base_uri,), PROJECT_LIMIT, PROJECT_THRESHOLD),
            ("Promoted global knowledge", (GLOBAL_URI,), GLOBAL_LIMIT, GLOBAL_THRESHOLD),
            (
                "Candidate memory",
                (INBOX_URI, CLASSIFIED_URI),
                CANDIDATE_LIMIT,
                CANDIDATE_THRESHOLD,
            ),
        )
        sections = []
        for title, uris, limit, threshold in searches:
            records_by_uri = {}
            search_limit = CANDIDATE_SCOPE_SCAN_LIMIT if title == "Candidate memory" else limit
            for uri in uris:
                for record_uri, score, record in self._search(
                    prompt,
                    uri,
                    limit=search_limit,
                    threshold=threshold,
                    after=after,
                    before=before,
                    include_scoped_tree=show_all,
                ):
                    if (
                        title == "Candidate memory"
                        and (
                            record["repository_id"] != self.repository_id
                            or record["status"] in INACTIVE_STATUSES
                        )
                    ):
                        continue
                    previous = records_by_uri.get(record_uri)
                    if previous is None or score > previous[0]:
                        records_by_uri[record_uri] = (score, record)
            records = sorted(
                (
                    (record_uri, score, record)
                    for record_uri, (score, record) in records_by_uri.items()
                ),
                key=lambda item: item[1],
                reverse=True,
            )[:limit]
            lines = []
            for record_uri, score, record in records:
                lines.append(
                    f"- {record['id']}: {record['content']}\n"
                    f"  Status: {record['status']}; URI: {record_uri}; Repository: "
                    f"{record['repository_id'] or 'global'}; Created: {record['created_at']}; "
                    f"Last verified: {record['last_verified_at'] or 'never'}; "
                    f"Review after: {record['review_after'] or 'none'}; "
                    f"Expires: {record['expires_at'] or 'none'}; Confidence: {record['confidence']}; "
                    f"Promotion: {record['promotion_mode'] or 'none'}; Similarity: {score:.3f}"
                )
            sections.append(f"## {title}\n" + ("\n".join(lines) if lines else "(none)"))
        return "\n\n".join(sections)

    # --- review sessions and harvest ------------------------------------------

    def record_review_session(self, session_client, outcome: "ReviewOutcome", *, now: datetime, token: str) -> dict:
        """Write one review's outcome as a committed OpenViking session.

        Nothing here touches the policy namespace: a session is raw experience
        for OpenViking's extractor, not a memory record. A review in which
        nothing happened is skipped without contacting OpenViking at all.
        """
        if not outcome.worth_recording:
            return {"status": "skipped", "reason": "nothing to learn from this review"}
        session_client.health()
        session_id = f"{SESSION_ID_PREFIX}{now.astimezone(timezone.utc):%Y%m%dT%H%M%SZ}-{token}"
        tags = {"source": SESSION_SOURCE_TAG, "kind": "code-review"}
        session_client.session_new(session_id, tags)
        session_client.session_add_messages(session_id, review_session_messages(self.repository_id, outcome))
        commit = session_client.session_commit(session_id, tags)
        # Facts about the outcome, for automatic promotion to check later. The
        # session text above is for OpenViking's extractor; this manifest is
        # what inhousecode trusts, because it is written by inhousecode itself.
        manifest = {
            "session_id": session_id,
            "repository_id": self.repository_id,
            "review_id": outcome.review_id,
            "recorded_at": now.astimezone(timezone.utc).isoformat(),
            "verdict": outcome.verdict,
            "overridden": bool(outcome.override_reason) or outcome.verdict == "overridden",
            "resolved": [
                {"gate": item.gate, "severity": item.severity, "location": item.location,
                 "category": item.category}
                for item in outcome.resolved[:MAX_RECORDED_RESOLVED]
            ],
            "still_open_count": len(outcome.still_open),
        }
        self.client.write(
            self.review_session_uri(session_id),
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        )
        return {
            "status": "recorded",
            "session_id": session_id,
            "user": getattr(session_client, "user", None),
            "task_id": commit.get("task_id"),
        }

    def review_session_uri(self, session_id: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", session_id).strip("-") or "session"
        return self.project_base_uri + REVIEW_SESSIONS_DIR + safe + ".json"

    def _exists(self, uri: str) -> bool:
        try:
            self.client.read(uri)
            return True
        except NotFound:
            return False

    def harvest_sessions(
        self,
        session_client,
        *,
        lookback_days: int,
        now: datetime,
        auto_promote_after: int = 0,
        code_exists: Callable[[str], bool] | None = None,
    ) -> dict:
        """Turn what OpenViking extracted from review sessions into candidates.

        Reads each archive's memory_diff.json -- the extractor's own audit log of
        what it added -- rather than the merged memory files, so every candidate
        traces to the exact session archive that produced it. Candidate IDs are
        content hashes, so a re-run (or a second machine) creates nothing new.
        """
        session_client.health()
        self.client.health()
        if lookback_days < 1:
            raise RecordError("lookback must be at least one day")
        if auto_promote_after == 1 or auto_promote_after < 0:
            raise RecordError("automatic promotion threshold must be 0 or at least 2")
        cutoff = now - timedelta(days=lookback_days)
        summary = {
            "sessions_scanned": 0,
            "archives_read": 0,
            "archives_pending": 0,
            "archives_malformed": 0,
            "created": 0,
            "quarantined": 0,
            "existing": 0,
            "candidates": [],
            "auto_promotion": [],
        }
        observations: dict[str, dict] = {}
        for session in session_client.session_list():
            modified = _parse_ov_time(str(session.get("mod_time") or ""))
            if modified is not None and modified < cutoff:
                continue
            session_id = str(session.get("session_id") or "").strip()
            if not session_id:
                continue
            session_uri = str(session.get("uri") or "").rstrip("/") or (
                f"viking://user/{getattr(session_client, 'user', 'unknown')}/sessions/{session_id}"
            )
            summary["sessions_scanned"] += 1
            for archive_uri in self._session_archives(session_client, session_uri):
                self._harvest_archive(
                    session_client, archive_uri, session_id, summary, observations
                )
        if auto_promote_after:
            locator = code_exists or (lambda _location: False)
            for observation in observations.values():
                decision = self._auto_promote_lesson(
                    observation,
                    threshold=auto_promote_after,
                    code_exists=locator,
                )
                if decision is not None:
                    summary["auto_promotion"].append(decision)
        return summary

    @staticmethod
    def _session_archives(session_client, session_uri: str) -> list[str]:
        history = session_uri + "/history/"
        try:
            nodes = session_client.tree(history.rstrip("/"))
        except NotFound:
            return []
        archives = set()
        for node in nodes:
            uri = str(node.get("uri") or "")
            if not uri.startswith(history):
                continue
            name = uri[len(history):].split("/", 1)[0]
            if name.startswith("archive_"):
                archives.add(history + name)
        return sorted(archives)

    def _harvest_archive(
        self,
        session_client,
        archive_uri: str,
        session_id: str,
        summary: dict,
        observations: dict[str, dict],
    ) -> None:
        diff_uri = archive_uri + "/memory_diff.json"
        try:
            raw = session_client.read(diff_uri)
        except NotFound:
            # Extraction runs in the background after commit; the next run
            # picks this archive up once it has finished.
            summary["archives_pending"] += 1
            return
        try:
            items = harvest_items(json.loads(raw))
        except (json.JSONDecodeError, RecordError):
            summary["archives_malformed"] += 1
            return
        summary["archives_read"] += 1
        for category, sentence in items:
            harvested = self._harvest_item(
                category, sentence, [archive_uri, diff_uri], summary
            )
            if harvested is None:
                continue
            key = lesson_key(sentence)
            observation = observations.setdefault(
                key,
                {
                    "candidate_id": harvested["id"],
                    "candidate_uri": harvested["uri"],
                    "sentence": sentence,
                    "sessions": {},
                    "categories": set(),
                },
            )
            observation["categories"].add(category)
            observation["sessions"].setdefault(session_id, []).extend(
                [archive_uri, diff_uri]
            )

    def _harvest_item(
        self, category: str, sentence: str, evidence: list[str], summary: dict
    ) -> dict | None:
        digest = hashlib.sha256(
            f"{self.repository_id}\0{HARVEST_SOURCE}\0{lesson_key(sentence)}".encode("utf-8")
        ).hexdigest()[:20]
        record_id = "candidate-" + digest
        filename = record_id + ".json"
        classified_uri = CLASSIFIED_URI + filename
        if self._exists(classified_uri):
            classified = parse_record(self.client.read(classified_uri))
            if classified["status"] == "promoted":
                summary["existing"] += 1
                return None
        existing_uri = next(
            (root + filename for root in (INBOX_URI, CLASSIFIED_URI, QUARANTINE_URI)
             if self._exists(root + filename)),
            None,
        )
        if existing_uri:
            summary["existing"] += 1
            if existing_uri.startswith(QUARANTINE_URI):
                return None
            return {"id": record_id, "uri": existing_uri}
        quarantined = looks_like_injection(sentence)
        record = new_record(
            record_id=record_id,
            memory_type="candidate",
            repository_id=self.repository_id,
            status="quarantined" if quarantined else "candidate",
            source=HARVEST_SOURCE,
            created_at=self.today().isoformat(),
            confidence="low" if quarantined else "medium",
            evidence=list(evidence) + [f"openviking-category:{category}"],
            content=sentence,
        )
        uri = (QUARANTINE_URI if quarantined else INBOX_URI) + filename
        self.client.write(uri, serialize_record(record))
        summary["quarantined" if quarantined else "created"] += 1
        summary["candidates"].append({"id": record_id, "uri": uri, "status": record["status"]})
        if quarantined:
            return None
        return {"id": record_id, "uri": uri}

    def _auto_promote_lesson(
        self,
        observation: dict,
        *,
        threshold: int,
        code_exists: Callable[[str], bool],
    ) -> dict | None:
        candidate_id = observation["candidate_id"]
        inbox_uri = self._candidate_inbox_uri(candidate_id)
        classified_uri = self._candidate_classified_uri(candidate_id)
        if self._exists(classified_uri):
            existing_candidate = parse_record(self.client.read(classified_uri))
            if existing_candidate["status"] == "promoted":
                return None
        source = parse_record(self.client.read(inbox_uri))

        qualifying: dict[str, dict] = {}
        all_evidence: list[str] = []
        finding_categories: set[str] = set()
        for session_id, extraction_evidence in observation["sessions"].items():
            manifest_uri = self.review_session_uri(session_id)
            try:
                manifest = json.loads(self.client.read(manifest_uri))
            except (NotFound, json.JSONDecodeError, TypeError):
                continue
            if manifest.get("repository_id") != self.repository_id or manifest.get("overridden"):
                continue
            valid_findings = [
                item for item in manifest.get("resolved", [])
                if isinstance(item, dict) and code_exists(str(item.get("location") or ""))
            ]
            if not valid_findings:
                continue
            qualifying[session_id] = manifest
            all_evidence.extend(extraction_evidence)
            all_evidence.append(manifest_uri)
            for item in valid_findings:
                location = str(item.get("location") or "")
                category = str(item.get("category") or "")
                all_evidence.append(f"{location} | {category} | review:{manifest.get('review_id', session_id)}")
                finding_categories.add(category)

        count = len(qualifying)
        sentence = source["content"]
        security_sensitive = is_security_related(sentence) or any(
            is_security_related(category) for category in finding_categories
        )
        changes_review_behavior = suppresses_findings(sentence)
        status = "awaiting_recurrence"
        reason = f"observed in {count} qualifying reviews; {threshold} required"
        related_uri = self._related_promoted_uri(sentence)
        if security_sensitive:
            status = "needs_human"
            reason = "security-related knowledge requires human review"
        elif changes_review_behavior:
            status = "needs_human"
            reason = "knowledge that changes review behavior requires human review"
        elif related_uri == "identical":
            status = "already_known"
            reason = "identical promoted knowledge already exists"
        elif related_uri:
            status = "needs_human"
            reason = f"potentially conflicts with or duplicates promoted knowledge at {related_uri}"
        elif count >= threshold:
            status = "promoted"
            reason = f"safe repository-local lesson confirmed by {count} separate reviews"

        evidence = list(dict.fromkeys(all_evidence))
        classified = dict(source)
        classified.update(
            {
                "status": "promoted" if status == "promoted" else "classified",
                "confidence": "high" if count >= threshold else "medium",
                "evidence": evidence,
                "promotion_mode": "automatic" if status == "promoted" else None,
                "promotion_reason": reason,
                "promoted_to": None,
                "promoted_at": self.today().isoformat() if status == "promoted" else None,
            }
        )
        promoted_uri = None
        if status == "promoted":
            promoted = new_record(
                record_id="project-" + candidate_id.removeprefix("candidate-"),
                memory_type="project",
                repository_id=self.repository_id,
                status="promoted",
                source=source["source"],
                created_at=self.today().isoformat(),
                last_verified_at=self.today().isoformat(),
                confidence="high",
                evidence=evidence + [inbox_uri],
                promotion_mode="automatic",
                promotion_reason=reason,
                promoted_at=self.today().isoformat(),
                content=sentence,
            )
            promoted_uri = self.project_uri(promoted["id"] + ".json")
            self.client.write(promoted_uri, serialize_record(promoted))
            classified["promoted_to"] = promoted_uri
        self.client.write(classified_uri, serialize_record(classified))
        return {
            "candidate_id": candidate_id,
            "status": status,
            "qualifying_reviews": count,
            "reason": reason,
            "promoted_uri": promoted_uri,
        }

    def _related_promoted_uri(self, sentence: str) -> str | None:
        words = content_words(sentence)
        for root in (self.project_base_uri, GLOBAL_URI):
            try:
                nodes = self.client.tree(root.rstrip("/"))
            except NotFound:
                nodes = []
            for node in nodes:
                uri = str(node.get("uri") or "")
                if not uri or uri.endswith("README.md"):
                    continue
                try:
                    record = parse_record(self.client.read(uri))
                except (NotFound, RecordError):
                    continue
                if record["status"] != "promoted":
                    continue
                if lesson_key(record["content"]) == lesson_key(sentence):
                    return "identical"
                if len(words & content_words(record["content"])) >= CONFLICT_MIN_SHARED_WORDS:
                    return uri
        return None


def review_content_summary(
    repo_root: Path,
    changed_paths: list[str],
    *,
    review_type: str,
    diff_summary: str,
) -> str:
    """Give semantic retrieval source text when a path review has no diff."""
    if diff_summary.strip() or review_type != "path":
        return diff_summary

    root = repo_root.resolve()
    blocks: list[str] = []
    used = 0
    for relative in changed_paths:
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        try:
            content = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "\x00" in content:
            continue
        block = f"File {relative}:\n{content}"
        remaining = PATH_REVIEW_QUERY_MAX_CHARS - used
        if remaining <= 0:
            break
        blocks.append(block[:remaining])
        used += len(blocks[-1])
    return "\n\n".join(blocks)


def build_review_query(
    repository_id: str,
    *,
    changed_paths: list[str],
    changed_symbols: list[str],
    diff_summary: str,
    review_type: str,
) -> str:
    parts = [f"Review {review_type} changes in {repository_id}."]
    if changed_paths:
        parts.append("Changed paths: " + ", ".join(changed_paths[:30]) + ".")
    if changed_symbols:
        parts.append("Changed symbols: " + ", ".join(changed_symbols[:30]) + ".")
    if diff_summary.strip():
        parts.append("Diff summary: " + " ".join(diff_summary.split())[:1000] + ".")
    parts.append("Check repository conventions, required tests, known exceptions, and relevant risks.")
    return " ".join(parts)


def make_policy(repo_root: Path) -> MemoryPolicy:
    return MemoryPolicy(OpenVikingClient(), repository_id_for(repo_root))


# --- review sessions -----------------------------------------------------------


def session_user_for(repository_id: str, environ: dict[str, str]) -> str:
    """The OpenViking user that owns this repository's review sessions.

    Dedicated so OpenViking's extractor never writes review lessons into a
    developer's personal memories, and so the harvest never reads them. One user
    per repository keeps the extracted experience scoped to that repository.
    """
    override = (environ.get(SESSION_USER_ENV) or "").strip()
    if override:
        if override.lower() in RESERVED_SESSION_USERS or not SESSION_USER_PATTERN.match(override):
            raise RecordError(f"{SESSION_USER_ENV} must be a dedicated user name, not {override!r}")
        return override
    digest = hashlib.sha256(repository_id.encode("utf-8")).hexdigest()[:12]
    return SESSION_USER_PREFIX + digest


def clean_text(value: str) -> str:
    return CONTROL_CHARS.sub("", value or "")


class Finding:
    """One contract-shaped finding line: marker, severity, location, category, fix."""

    def __init__(self, gate: str, severity: str, location: str, category: str, fix: str):
        self.gate = gate
        self.severity = severity
        self.location = location
        self.category = category
        self.fix = fix

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.gate, self.location, self.category)

    def describe(self) -> str:
        return f"[{self.gate}][{self.severity}] {self.location} ({self.category}): {self.fix}"


def parse_findings(report: str) -> list[Finding]:
    found = []
    for line in clean_text(report).splitlines():
        fields = line.split("\t")
        if len(fields) < 5 or fields[0].strip() not in FINDING_MARKERS:
            continue
        gate = "static" if fields[0].strip() == "##STATIC-FINDING##" else "review"
        found.append(Finding(gate, *(field.strip() for field in fields[1:5])))
    return found


class ReviewOutcome:
    """What happened in one review run, as facts a model can learn from."""

    def __init__(
        self,
        *,
        review_id: str,
        target: str,
        verdict: str,
        initial_ai: str,
        final_ai: str,
        initial_static: str,
        final_static: str,
        override_reason: str,
        preferences: str,
        fix_rounds: int,
    ):
        self.review_id = clean_text(review_id).strip() or "review"
        self.target = clean_text(target).strip() or "unknown"
        self.verdict = clean_text(verdict).strip() or "unknown"
        self.override_reason = clean_text(override_reason).strip()
        self.preferences = clean_text(preferences).strip()
        self.fix_rounds = max(0, int(fix_rounds))
        initial = parse_findings(initial_static) + parse_findings(initial_ai)
        final = parse_findings(final_static) + parse_findings(final_ai)
        final_keys = {item.key for item in final}
        self.resolved = [item for item in initial if item.key not in final_keys]
        self.still_open = final

    @property
    def worth_recording(self) -> bool:
        return bool(self.resolved or self.still_open or self.override_reason or self.preferences)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def review_session_messages(repository_id: str, outcome: ReviewOutcome) -> list[dict]:
    """Two plain messages: what the reviewer saw, and how it ended.

    Stated as facts rather than instructions so the extractor records experience
    ("in this repository X was fixed by Y") and never an order to follow.
    """
    lines = [
        f"Code review of repository {repository_id} ({outcome.target}, review {outcome.review_id}).",
        f"Final verdict: {outcome.verdict}. Automatic repair rounds: {outcome.fix_rounds}.",
    ]
    if outcome.resolved:
        lines.append("Resolved during this review (flagged, then fixed):")
        lines += ["- " + item.describe() for item in outcome.resolved[:SESSION_MAX_FINDINGS]]
    if outcome.still_open:
        lines.append("Still open at the end of the review:")
        lines += ["- " + item.describe() for item in outcome.still_open[:SESSION_MAX_FINDINGS]]
    if outcome.override_reason:
        lines.append("The developer overrode the blocked verdict. Stated reason: " + outcome.override_reason)
    if outcome.preferences:
        lines.append("Team preference the developer recorded: " + outcome.preferences)
    closing = (
        "Outcome recorded for learning. Findings that were resolved show what this "
        "repository considers a real defect; overrides and preferences show what it "
        "deliberately accepts."
    )
    budget = SESSION_MAX_CHARS - len(closing)
    return [
        {"role": "user", "content": _clip("\n".join(lines), budget)},
        {"role": "assistant", "content": closing},
    ]


class OpenVikingSessionClient(OpenVikingClient):
    """OpenViking CLI calls made as the dedicated review-session user."""

    def __init__(self, user: str, binary: str | None = None, env: dict[str, str] | None = None):
        super().__init__(binary, env)
        self.user = user

    def _as_user(self, arguments: list[str]) -> object:
        return self._run(["--user", self.user, *arguments])

    @staticmethod
    def _tags(tags: dict[str, str]) -> str:
        return ",".join(f"{key}={value}" for key, value in sorted(tags.items()))

    def session_new(self, session_id: str, tags: dict[str, str]) -> None:
        self._as_user(
            ["session", "new", "--session-id", session_id, "--no-auto-commit", "--event-tags", self._tags(tags)]
        )

    def session_add_messages(self, session_id: str, messages: list[dict]) -> None:
        self._as_user(["session", "add-messages", session_id, json.dumps(messages, ensure_ascii=False)])

    def session_commit(self, session_id: str, tags: dict[str, str]) -> dict:
        result = self._as_user(["session", "commit", session_id, "--event-tags", self._tags(tags)])
        return result if isinstance(result, dict) else {}

    def session_list(self) -> list[dict]:
        result = self._as_user(["session", "list"])
        return result if isinstance(result, list) else []

    def tree(self, uri: str) -> list[dict]:
        result = self._as_user(["tree", uri, "--all", "--level-limit", "4", "--node-limit", "1000"])
        return result if isinstance(result, list) else []

    def read(self, uri: str) -> str:
        result = self._as_user(["read", uri])
        if not isinstance(result, str):
            raise OpenVikingError(f"OpenViking returned non-text content for {uri}")
        return result


def _parse_ov_time(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    # Python 3.9's fromisoformat rejects fractional seconds other than 3 or 6
    # digits, which OpenViking does emit; drop them -- second precision is enough.
    text = re.sub(r"(\d{2}:\d{2}:\d{2})\.\d+", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def harvest_items(diff: dict) -> list[tuple[str, str]]:
    """(category, sentence) pairs that a commit's extraction added.

    For an update only the lines absent from ``before`` are new; re-harvesting
    the unchanged part of a merged memory file would create duplicates.
    """
    operations = diff.get("operations") if isinstance(diff, dict) else None
    if not isinstance(operations, dict):
        raise RecordError("memory_diff.json has no operations object")
    items = []
    for operation in list(operations.get("adds") or []) + list(operations.get("updates") or []):
        if not isinstance(operation, dict):
            continue
        category = str(operation.get("memory_type") or "").strip().lower()
        if category not in HARVEST_CATEGORIES:
            continue
        before = {_normalize_item(line) for line in str(operation.get("before") or "").splitlines()}
        for line in str(operation.get("after") or "").splitlines():
            sentence = _normalize_item(line)
            if len(sentence) < HARVEST_MIN_ITEM_CHARS or sentence in before:
                continue
            items.append((category, _clip(sentence, HARVEST_MAX_ITEM_CHARS)))
    return items


def _normalize_item(line: str) -> str:
    text = clean_text(line).strip()
    if text.startswith("#"):
        return ""
    text = re.sub(r"^([-*+]|\d+[.)])\s+", "", text)
    return " ".join(text.split())


def lesson_key(sentence: str) -> str:
    """The identity of a lesson: case, spacing, and edge punctuation ignored.

    OpenViking rewords freely, so exact text would split one lesson into many
    and nothing would ever recur. Anything beyond this (synonyms, reordering)
    is deliberately not merged: a false merge would promote a lesson nobody
    actually repeated.
    """
    text = " ".join(sentence.lower().split())
    return text.strip(" .;:!?,\"'`")


def content_words(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9_]+", text.lower())
        if len(word) > 2 and word not in STOPWORDS
    }


def is_security_related(text: str) -> bool:
    return bool(SECURITY_TERMS.search(text))


def suppresses_findings(text: str) -> bool:
    return bool(SUPPRESSION_TERMS.search(text))


LOCATION_PATTERN = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+)")


def make_code_locator(repo_root: Path) -> Callable[[str], bool]:
    """A check that a finding's ``path:line`` is real code in this repository.

    Paths that escape the repository (``..`` or absolute) never count: a lesson
    may only be promoted on evidence inside the repository it is promoted for.
    """
    root = Path(repo_root).resolve()

    def exists(location: str) -> bool:
        match = LOCATION_PATTERN.match((location or "").strip())
        if not match:
            return False
        line = int(match.group("line"))
        if line < 1:
            return False
        try:
            target = (root / match.group("path")).resolve()
            target.relative_to(root)
        except (OSError, ValueError):
            return False
        if not target.is_file():
            return False
        try:
            with target.open("rb") as handle:
                count = sum(1 for _ in handle)
        except OSError:
            return False
        return line <= count

    return exists


def looks_like_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in INJECTION_PATTERNS)


OUTCOME_ENV_PREFIX = "INHOUSECODE_OUTCOME_"


def outcome_from_env(environ: dict[str, str]) -> ReviewOutcome:
    """Read a review outcome handed over by the Bash orchestrator.

    Environment variables rather than a temporary file: nothing about a review
    outcome is ever persisted locally, and findings contain tabs and quotes that
    argv would need escaping for.
    """

    def get(name: str) -> str:
        return environ.get(OUTCOME_ENV_PREFIX + name, "")

    try:
        fix_rounds = int(get("FIX_ROUNDS") or 0)
    except ValueError:
        fix_rounds = 0
    return ReviewOutcome(
        review_id=get("REVIEW_ID"),
        target=get("TARGET"),
        verdict=get("VERDICT"),
        initial_ai=get("INITIAL_AI"),
        final_ai=get("FINAL_AI"),
        initial_static=get("INITIAL_STATIC"),
        final_static=get("FINAL_STATIC"),
        override_reason=get("OVERRIDE_REASON"),
        preferences=get("PREFERENCES"),
        fix_rounds=fix_rounds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", type=Path)
    parser.add_argument(
        "command",
        choices=(
            "init", "check", "candidate-add", "view", "context", "classify", "promote", "migrate",
            "session-record", "harvest",
        ),
    )
    parser.add_argument("args", nargs="*")
    parser.add_argument("--prompt", default="")
    parser.add_argument("--review-id", default="review")
    parser.add_argument("--review-type", default="code review")
    parser.add_argument("--changed-files")
    parser.add_argument("--diff")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_CONTEXT_MAX_CHARS)
    parser.add_argument("--target", choices=("project", "global"), default="project")
    parser.add_argument("--confidence", choices=("low", "medium", "high"), default="medium")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--reason", default="")
    parser.add_argument("--source", default="developer")
    parser.add_argument(
        "--source-uri",
        default="viking://user/default/resources/memory-policy",
    )
    parser.add_argument("--scope-unclear", action="store_true")
    parser.add_argument("--conflict", action="store_true")
    parser.add_argument("--security-sensitive", action="store_true")
    parser.add_argument("--affects-review-behavior", action="store_true")
    parser.add_argument("--cross-repository", action="store_true")
    parser.add_argument("--lookback-days", type=int, default=HARVEST_DEFAULT_LOOKBACK_DAYS)
    parser.add_argument(
        "--auto-promote-after",
        type=int,
        default=0,
        help="promote a safe recurring lesson after N separate reviews; 0 disables",
    )
    parser.add_argument("--expires-at", default=None, help="YYYY-MM-DD; record stops applying after this date")
    parser.add_argument("--review-after", default=None, help="YYYY-MM-DD; record is flagged for revalidation after this date")
    parsed = parser.parse_intermixed_args()
    try:
        policy = make_policy(parsed.repo_root)
        if parsed.command in ("session-record", "harvest"):
            session_client = OpenVikingSessionClient(
                session_user_for(policy.repository_id, dict(os.environ))
            )
            now = datetime.now(timezone.utc)
            if parsed.command == "session-record":
                result = policy.record_review_session(
                    session_client,
                    outcome_from_env(dict(os.environ)),
                    now=now,
                    token=os.urandom(4).hex(),
                )
            else:
                result = policy.harvest_sessions(
                    session_client,
                    lookback_days=parsed.lookback_days,
                    now=now,
                    auto_promote_after=parsed.auto_promote_after,
                    code_exists=make_code_locator(parsed.repo_root),
                )
            print(json.dumps(result, sort_keys=True, ensure_ascii=False))
            return 0
        if parsed.command == "init":
            policy.initialize()
            print(f"inhousecode memory: initialized {ROOT_URI}/")
            return 0
        if parsed.command == "check":
            policy.client.health()
            policy.client.tree(ROOT_URI)
            print(f"inhousecode memory: OpenViking healthy; namespace readable at {ROOT_URI}/")
            return 0
        if parsed.command == "migrate":
            migrated = migrate_legacy_namespace(policy.client, policy, parsed.source_uri)
            print(json.dumps({"migrated": migrated}, sort_keys=True, ensure_ascii=False))
            return 0
        if parsed.command == "candidate-add":
            if len(parsed.args) != 1:
                parser.error("candidate-add requires one text argument")
            record, uri = policy.add_candidate(
                parsed.args[0], source=parsed.source, evidence=parsed.evidence
            )
            print(json.dumps({"id": record["id"], "uri": uri}, sort_keys=True))
            return 0
        if parsed.command == "view":
            if not parsed.prompt:
                parser.error("view requires --prompt")
            print(policy.view(parsed.prompt))
            return 0
        if parsed.command == "context":
            paths = []
            if parsed.changed_files:
                try:
                    paths = [line.strip() for line in Path(parsed.changed_files).read_text(encoding="utf-8").splitlines() if line.strip()]
                except OSError as error:
                    raise OpenVikingError(f"could not read changed-files input: {error}") from error
            diff_summary = ""
            if parsed.diff:
                try:
                    diff_summary = Path(parsed.diff).read_text(encoding="utf-8")[:4000]
                except OSError as error:
                    raise OpenVikingError(f"could not read diff input: {error}") from error
            diff_summary = review_content_summary(
                parsed.repo_root,
                paths,
                review_type=parsed.review_type,
                diff_summary=diff_summary,
            )
            query = parsed.prompt or build_review_query(
                policy.repository_id,
                changed_paths=paths,
                changed_symbols=[],
                diff_summary=diff_summary,
                review_type=parsed.review_type,
            )
            snapshot = policy.build_context(
                query=query,
                review_id=parsed.review_id,
                max_chars=parsed.max_chars,
            )
            print(json.dumps(snapshot, sort_keys=True, ensure_ascii=False))
            return 0
        if parsed.command == "classify":
            if len(parsed.args) != 1:
                parser.error("classify requires one candidate ID")
            result = policy.classify_candidate(
                parsed.args[0],
                target=parsed.target,
                confidence=parsed.confidence,
                evidence=parsed.evidence,
                scope_clear=not parsed.scope_unclear,
                conflict=parsed.conflict,
                security_sensitive=parsed.security_sensitive,
                affects_review_behavior=parsed.affects_review_behavior,
                cross_repository=parsed.cross_repository,
                expires_at=parsed.expires_at,
                review_after=parsed.review_after,
            )
            print(json.dumps(result, sort_keys=True, ensure_ascii=False))
            return 0
        if len(parsed.args) != 1 or not parsed.reason:
            parser.error("promote requires one candidate ID and --reason")
        result = policy.promote_candidate(
            parsed.args[0],
            target=parsed.target,
            reason=parsed.reason,
            evidence=parsed.evidence,
            expires_at=parsed.expires_at,
            review_after=parsed.review_after,
        )
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (OpenVikingError, RecordError, ValueError) as error:
        print(f"inhousecode memory: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
