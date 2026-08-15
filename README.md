# GitHub Actions log parser CLI

Small, dependency-free Python CLI prepared for WorkProtocol job `f82a9ca9-4b7f-4bdf-91c1-b5ae0516b4eb`.

It accepts a GitHub Actions run URL, downloads the official logs archive, and prints a deterministic JSON summary containing the failing step, first useful error, stack/error context, failure type, and a suggested fix category. It recognizes test (pytest/Jest), build/TypeScript, and lint failures.

## Install and use

```powershell
python -m pip install .
$env:GITHUB_TOKEN = "<optional token for private repos>"
gh-actions-log-parser https://github.com/owner/repository/actions/runs/123
```

The token is read only at runtime and is never written to logs or state. Public runs may work without a token. A successful result looks like:

```json
{
  "error_message": "FAILED tests/test_api.py::test_bad",
  "failure_type": "test",
  "failing_step_name": "Run tests",
  "source_files": ["2_Run_tests.txt"],
  "stack_trace": ["pytest", "FAILED tests/test_api.py::test_bad"],
  "status": "failed",
  "suggested_fix_category": "test failure"
}
```

Invalid URLs, HTTP failures, empty archives, and malformed ZIP responses return a concise error on stderr and exit with code `2`.

## Tests and quality

```powershell
$py = "C:\Users\abian\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py -m unittest discover -s tests -v
pylint src
```

Tests use mocked GitHub responses and in-memory ZIP archives; they never contact GitHub. The external job requires a public repository, at least five tests, type hints on public functions, and pylint >= 8.0. No submission or payment is claimed until WorkProtocol reports verified delivery and a Base settlement transaction.

