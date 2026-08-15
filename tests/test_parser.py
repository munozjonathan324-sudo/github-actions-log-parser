"""Deterministic tests for URL parsing, archive handling, and classification."""

from __future__ import annotations

import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from gh_actions_parser.parser import (  # noqa: E402
    GitHubClient,
    ParserError,
    decode_log_archive,
    parse_run_url,
    summarize_logs,
)


def make_archive(entries: dict[str, str]) -> bytes:
    """Build a deterministic in-memory ZIP fixture."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class ParserTests(unittest.TestCase):
    """Cover the acceptance criteria and representative errors."""

    def test_parse_run_url(self) -> None:
        reference = parse_run_url("https://github.com/acme/api/actions/runs/12345")
        self.assertEqual((reference.owner, reference.repository, reference.run_id), ("acme", "api", 12345))

    def test_rejects_non_github_url(self) -> None:
        with self.assertRaises(ParserError):
            parse_run_url("https://example.com/acme/api/actions/runs/1")

    def test_decodes_archive_and_classifies_pytest(self) -> None:
        payload = make_archive({"2_Run_tests.txt": "pytest\nFAILED tests/test_api.py::test_bad\nAssertionError: 2 != 3"})
        summary = summarize_logs(decode_log_archive(payload))
        self.assertEqual(summary.failure_type, "test")
        self.assertEqual(summary.suggested_fix_category, "test failure")
        self.assertEqual(summary.failing_step_name, "Run tests")

    def test_classifies_typescript_build(self) -> None:
        summary = summarize_logs({"3_Build.txt": "npm run build\nerror TS2322: Type mismatch"})
        self.assertEqual(summary.failure_type, "build")
        self.assertIn("TS2322", summary.error_message or "")

    def test_classifies_lint(self) -> None:
        summary = summarize_logs({"4_Lint.txt": "eslint src/app.ts\nerror  no-unused-vars"})
        self.assertEqual(summary.failure_type, "lint")
        self.assertEqual(summary.suggested_fix_category, "linting")

    def test_passed_run_has_no_failure(self) -> None:
        summary = summarize_logs({"1_Set_up_job.txt": "Set up job\ncompleted successfully"})
        self.assertEqual(summary.status, "passed")
        self.assertIsNone(summary.error_message)

    def test_client_uses_mocked_api_transport_and_token(self) -> None:
        captured: dict[str, object] = {}

        def transport(url: str, headers: dict[str, str]) -> bytes:
            captured["url"] = url
            captured["headers"] = headers
            return make_archive({"1_Test.txt": "jest\nFAIL src/app.test.ts"})

        client = GitHubClient(token="fixture-placeholder", transport=transport)
        summary = summarize_logs(client.download_logs(parse_run_url("https://github.com/a/b/actions/runs/9")))
        self.assertEqual(summary.failure_type, "test")
        self.assertIn("/repos/a/b/actions/runs/9/logs", str(captured["url"]))
        self.assertEqual(captured["headers"]["Authorization"], "Bearer fixture-placeholder")

    def test_invalid_archive_is_rejected(self) -> None:
        with self.assertRaises(ParserError):
            decode_log_archive(b"not-a-zip")

    def test_mocked_api_error_archive_is_rejected(self) -> None:
        client = GitHubClient(transport=lambda _url, _headers: b"upstream-error")
        reference = parse_run_url("https://github.com/a/b/actions/runs/10")
        with self.assertRaises(ParserError):
            client.download_logs(reference)

    def test_mocked_api_empty_response_is_rejected(self) -> None:
        client = GitHubClient(transport=lambda _url, _headers: b"")
        reference = parse_run_url("https://github.com/a/b/actions/runs/11")
        with self.assertRaises(ParserError):
            client.download_logs(reference)


if __name__ == "__main__":
    unittest.main()

