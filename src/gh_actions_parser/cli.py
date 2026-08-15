"""Command-line entry point for the GitHub Actions log parser."""

from __future__ import annotations

import argparse
import sys

from .parser import ParserError, parse_run, summary_json


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(description="Summarize a GitHub Actions run failure as JSON.")
    parser.add_argument("run_url", help="GitHub Actions run URL")
    parser.add_argument(
        "--token",
        default=None,
        help="optional GitHub token (GITHUB_TOKEN is used when omitted)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    args = build_parser().parse_args(argv)
    try:
        print(summary_json(parse_run(args.run_url, token=args.token)))
    except ParserError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

