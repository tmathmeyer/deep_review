"""
Command Line Interface and Orchestrator for the Code Review System.
"""

import argparse
import asyncio
import os
import sys
from vync import Vync

from core.gemini_client import GeminiClient
from hosts.host import Host
from hosts import GetCodeHosts


def GetArguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Automated LLM-based Code Review System"
    )
    parser.add_argument("url", help="Gerrit CL URL, GitHub PR URL, or 'local'")
    parser.add_argument(
        "--out-dir", type=str, help="Directory to save files (defaults to reviews/<id>)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3-flash-preview",
        help="The Gemini model to use for analysis and review (default: gemini-3-flash-preview)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock agents and gemini-3.1-flash-lite-preview for faster testing",
    )
    return parser.parse_args()


def SelectCodeHost(code_ref: str) -> Host:
    for host_option in GetCodeHosts():
        if host := host_option.CreateFromRef(code_ref):
            return host
    return None


async def main_async():
    args = GetArguments()

    if not (implementation := SelectCodeHost(args.url)):
        print(f"Error, could not parse {args.url}")
        sys.exit(1)

    if not (api_key := os.environ.get("GEMINI_API_KEY")):
        print("Error: GEMINI_API_KEY not set in environment")
        sys.exit(1)

    gemini_client = GeminiClient(api_key=api_key)
    implementation.ConfigureModel(args, gemini_client)

    synchronizer = Vync()
    for label, task in implementation.Steps():
        await synchronizer.TrackAndAwait(label, task(synchronizer))


if __name__ == "__main__":
    asyncio.run(main_async())
