"""Fetch and classify GitHub Actions run logs without third-party packages."""

from __future__ import annotations

import io
import json
import os
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse


class ParserError(ValueError):
    """Raised when a run URL, response, or log archive is invalid."""


@dataclass(frozen=True)
class RunReference:
    """The repository and run identifier extracted from a public URL."""

    owner: str
    repository: str
    run_id: int


@dataclass(frozen=True)
class FailureSummary:
    """Stable JSON-friendly representation of a run result."""

    status: str
    failing_step_name: str | None
    error_message: str | None
    stack_trace: list[str]
    suggested_fix_category: str | None
    failure_type: str | None
    source_files: list[str]

    def to_dict(self) -> dict[str, object]:
        """Return the summary as a JSON-serializable dictionary."""

        return asdict(self)


Transport = Callable[[str, Mapping[str, str]], bytes]


_RUN_PATH = re.compile(r"^/([^/]+)/([^/]+)/actions/runs/(\d+)(?:/.*)?/?$")
_ERROR_LINE = re.compile(
    r"(?i)(?:\bfailed\b|\bfail\b|\berror\b|\bexception\b|"
    r"assertionerror|traceback|\bts\d{3,5}\b|module not found)"
)


def parse_run_url(run_url: str) -> RunReference:
    """Parse a GitHub Actions run URL and reject unrelated hosts/paths."""

    parsed = urlparse(run_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ParserError("run_url must be a github.com URL")
    match = _RUN_PATH.match(parsed.path)
    if not match:
        raise ParserError("run_url must match /owner/repository/actions/runs/{id}")
    owner, repository, run_id_text = match.groups()
    run_id = int(run_id_text)
    if run_id <= 0:
        raise ParserError("run_id must be positive")
    return RunReference(owner, repository, run_id)


def _default_transport(url: str, headers: Mapping[str, str]) -> bytes:
    """Download one API response using the standard library."""

    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ParserError(f"GitHub API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ParserError(f"GitHub API request failed: {exc.reason}") from exc


class GitHubClient:
    """Small GitHub Actions logs client with injectable transport for tests."""

    def __init__(self, token: str | None = None, transport: Transport | None = None) -> None:
        self._token = token or os.getenv("GITHUB_TOKEN")
        self._transport = transport or _default_transport

    def download_logs(self, reference: RunReference) -> dict[str, str]:
        """Download and decode the ZIP archive returned by GitHub."""

        endpoint = (
            f"https://api.github.com/repos/{reference.owner}/{reference.repository}"
            f"/actions/runs/{reference.run_id}/logs"
        )
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "github-actions-log-parser/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        payload = self._transport(endpoint, headers)
        return decode_log_archive(payload)


def decode_log_archive(payload: bytes) -> dict[str, str]:
    """Decode a GitHub log ZIP into filename-to-text entries."""

    if not payload:
        raise ParserError("GitHub returned an empty log archive")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            entries = {
                name: archive.read(name).decode("utf-8", errors="replace")
                for name in archive.namelist()
                if not name.endswith("/") and name.lower().endswith((".txt", ".log"))
            }
    except (zipfile.BadZipFile, OSError) as exc:
        raise ParserError("GitHub response is not a readable ZIP log archive") from exc
    if not entries:
        raise ParserError("log archive contains no .txt or .log entries")
    return entries


def _classify(text: str) -> tuple[str, str, int]:
    """Return (failure type, category, priority) for one log."""

    lowered = text.lower()
    if any(marker in lowered for marker in ("eslint", "pylint", "flake8", "ruff", "lint")):
        return "lint", "linting", 3
    if any(marker in lowered for marker in ("typescript", "tsc", "error ts", "npm run build")):
        return "build", "build/compilation", 2
    if any(marker in lowered for marker in ("pytest", "jest", "assertionerror", "test suite")):
        return "test", "test failure", 1
    return "unknown", "general failure", 4


def _step_name(filename: str) -> str:
    """Turn GitHub's numbered log filename into a readable step name."""

    name = filename.rsplit("/", maxsplit=1)[-1]
    name = re.sub(r"^\d+[_-]?", "", name)
    name = re.sub(r"\.(?:txt|log)$", "", name, flags=re.IGNORECASE)
    return re.sub(r"[_-]+", " ", name).strip() or "unknown step"


def _error_lines(lines: Sequence[str]) -> list[int]:
    """Find likely error lines while preserving their original positions."""

    return [index for index, line in enumerate(lines) if _ERROR_LINE.search(line)]


def _stack_excerpt(lines: Sequence[str], error_index: int) -> list[str]:
    """Extract a bounded stack/error context around the strongest error line."""

    start = max(0, error_index - 2)
    end = min(len(lines), error_index + 9)
    excerpt = [line.rstrip() for line in lines[start:end] if line.strip()]
    return excerpt[:12]


def summarize_logs(logs: Mapping[str, str]) -> FailureSummary:
    """Classify the highest-priority failure found in a log mapping."""

    if not logs:
        raise ParserError("at least one log entry is required")
    candidates: list[tuple[int, str, str, str, list[str], str]] = []
    for filename in sorted(logs):
        lines = logs[filename].splitlines()
        indices = _error_lines(lines)
        if not indices:
            continue
        failure_type, category, priority = _classify(logs[filename])
        index = indices[0]
        message = lines[index].strip() or "failure detected"
        candidates.append(
            (priority, filename, failure_type, category, _stack_excerpt(lines, index), message)
        )
    if not candidates:
        return FailureSummary("passed", None, None, [], None, None, sorted(logs))
    _, filename, failure_type, category, excerpt, message = min(candidates)
    return FailureSummary(
        "failed",
        _step_name(filename),
        message,
        excerpt,
        category,
        failure_type,
        sorted(logs),
    )


def parse_run(run_url: str, token: str | None = None) -> FailureSummary:
    """Fetch a run's logs and return its structured failure summary."""

    reference = parse_run_url(run_url)
    return summarize_logs(GitHubClient(token=token).download_logs(reference))


def summary_json(summary: FailureSummary) -> str:
    """Serialize a summary with stable, human-readable JSON formatting."""

    return json.dumps(summary.to_dict(), indent=2, sort_keys=True)

