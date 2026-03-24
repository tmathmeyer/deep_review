"""
Command Line Interface and Orchestrator for the Code Review System.
"""

import sys
import os
import argparse
import shutil
import asyncio
from pathlib import Path
from vync import Vync

from core.gemini_client import GeminiClient
from core.change_fetcher import parse_gerrit_url
from backends import get_reviewer


def print_header(title: str):
    print(f"\n{'=' * 50}")
    print(f"--- {title} ---")
    print(f"{'=' * 50}")


async def main_async():
    parser = argparse.ArgumentParser(
        description="Automated LLM-based Code Review System"
    )
    parser.add_argument("url", help="Gerrit CL URL, GitHub PR URL, or 'local'")
    parser.add_argument(
        "--out-dir",
        type=str,
        help="Directory to save files (defaults to reviews/<target_id>)",
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

    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    target_id = args.url.replace("/", "_").replace(":", "_")
    if args.url.isdigit() or "googlesource" in args.url:
        try:
            _, target_id = parse_gerrit_url(args.url)
        except Exception:
            pass
    elif "github.com/" in args.url and "/pull/" in args.url:
        target_id = args.url.split("/")[-1]

    output_dir = Path(args.out_dir) if args.out_dir else Path("reviews") / target_id
    if output_dir.exists():
        print(f"Cleaning up existing directory: {output_dir}")
        shutil.rmtree(output_dir)

    gemini_client = GeminiClient(api_key=api_key)

    if args.mock:
        model_name = "gemini-3.1-flash-lite-preview"
        print("Running in MOCK mode (gemini-3.1-flash-lite-preview, mock_agents)")
    else:
        model_name = args.model

    try:
        reviewer = get_reviewer(args.url, gemini_client, model_name, args.mock)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    vync_app = Vync()

    try:
        # Step 1: Fetch Change
        print_header(f"Fetching Change {args.url}")

        change_info = await reviewer.fetch_change(args.url, output_dir, vync_app)

        if not change_info:
            print("Failed to fetch change info. Aborting.")
            sys.exit(1)

        # Step 2: Analyze Context
        print_header(f"Analyzing Context ({model_name})")
        analysis = await vync_app.TrackAndAwait(
            "Analyze Context",
            reviewer.perform_analysis(change_info, output_dir, vync_app),
        )

        if not analysis:
            print("Failed to analyze context. Aborting.")
            sys.exit(1)

        # Clean up project_tree so it doesn't pollute the review context
        project_tree_path = output_dir / "project_tree"
        if project_tree_path.exists():
            project_tree_path.unlink()

        # Step 3: Fetch Extra Context
        print_header("Loading Extra Context")
        await vync_app.TrackAndAwait(
            "Fetch Extra Context",
            reviewer.deduce_more_context(change_info, output_dir, vync_app),
        )

        # Step 4: Perform Review
        print_header(f"Performing Multi-Agent Code Review ({model_name})")

        agents_dir = reviewer.get_reviewer_agents_dir()
        num_agents = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0

        if num_agents == 0:
            print(f"No agents found in {agents_dir.name}. Skipping review.")
            sys.exit(0)

        await vync_app.TrackAndAwait(
            "Review Orchestrator",
            reviewer.run_review_agents(change_info, output_dir, vync_app),
        )

        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")
        final_summary = await vync_app.TrackAndAwait(
            "Summarize Reviews",
            reviewer.coalesce_reviews(change_info, output_dir, vync_app),
        )

        if final_summary:
            print(f"\n{reviewer.render_reviews(final_summary, output_dir)}\n")

        print(f"\n{'+' * 50}")
        print("SUCCESS: Pipeline complete!")
        print(
            f"Check the '{output_dir / 'final_summary.md'}' file for the final summary."
        )
        print(
            f"Check the '{output_dir / 'code_review.md'}' file for the full detailed review."
        )
        print(f"{'+' * 50}")

    except Exception as e:
        print(f"\n[!] Pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
    finally:
        vync_app.stop()


if __name__ == "__main__":
    asyncio.run(main_async())
