"""
Command Line Interface and Orchestrator for the Code Review System.
"""

import sys
import os
import time
import threading
import argparse
import shutil
import asyncio
from pathlib import Path
from vync import Vync

from core.gemini_client import GeminiClient
from core.change_fetcher import fetch_change, parse_gerrit_url
from core.context_analyzer import analyze_context
from core.extra_context_fetcher import fetch_extra_context
from core.review_engine import run_review
from core.review_summarizer import summarize_reviews
from core.render import render_markdown

def print_header(title: str):
    print(f"\n{'='*50}")
    print(f"--- {title} ---")
    print(f"{'='*50}")

def main():
    parser = argparse.ArgumentParser(description="Automated LLM-based Code Review System")
    parser.add_argument("url", help="Gerrit CL URL or numeric ID")
    parser.add_argument("--out-dir", type=str, help="Directory to save files (defaults to reviews/<CLID>)")
    parser.add_argument("--model", type=str, default="gemini-3-flash-preview",
                        help="The Gemini model to use for analysis and review (default: gemini-3-flash-preview)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock agents and gemini-3.1-flash-lite-preview for faster testing")

    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    try:
        _, cl_id = parse_gerrit_url(args.url)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    output_dir = Path(args.out_dir) if args.out_dir else Path("reviews") / cl_id
    if output_dir.exists():
        print(f"Cleaning up existing directory: {output_dir}")
        shutil.rmtree(output_dir)

    gemini_client = GeminiClient(api_key=api_key)

    if args.mock:
        model_name = "gemini-3.1-flash-lite-preview"
        agents_dir = Path(__file__).parent / "mock_agents"
        print("Running in MOCK mode (gemini-3.1-flash-lite-preview, mock_agents)")
    else:
        model_name = args.model
        agents_dir = Path(__file__).parent / "agents"

    vync_app = Vync()

    try:
        # Step 1: Fetch Change
        print_header(f"Fetching Change {cl_id}")
        change_info = fetch_change(args.url, output_dir, vync_app)

        # Step 2: Analyze Context
        print_header(f"Analyzing Context ({model_name})")
        analysis_ref = [None]
        async def _run_analysis():
            analysis_ref[0] = await analyze_context(output_dir, gemini_client, model_name, agents_dir)
        vync_app.TrackJob("Analyze Context", _run_analysis())
        vync_app.WaitAll()
        analysis = analysis_ref[0]

        if not analysis:
            print("Failed to analyze context. Aborting.")
            sys.exit(1)
            
        # Clean up project_tree so it doesn't pollute the review context
        project_tree_path = output_dir / "project_tree"
        if project_tree_path.exists():
            project_tree_path.unlink()

        # Step 3: Fetch Extra Context
        print_header("Loading Extra Context")
        fetch_extra_context(output_dir, change_info, analysis, vync_app)

        # Step 4: Perform Review
        print_header(f"Performing Multi-Agent Code Review ({model_name})")

        # Count agents to allocate dashboard space
        num_agents = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0

        if num_agents == 0:
            print(f"No agents found in {agents_dir.name}. Skipping review.")
            sys.exit(0)

        vync_app.TrackJob("Review Orchestrator", run_review(
                cl_dir=output_dir,
                gemini_client=gemini_client,
                model_name=model_name,
                agents_dir=agents_dir,
                vync_app=vync_app
            ))
        vync_app.WaitAll()

        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")

        summary_ref = [None]
        async def _track_summary():
            summary_ref[0] = await summarize_reviews(cl_dir=output_dir, gemini_client=gemini_client, model_name=model_name)
        vync_app.TrackJob("Summarize Reviews", _track_summary())
        vync_app.WaitAll()
        final_summary = summary_ref[0]

        if final_summary:
            print(f"\n{render_markdown(final_summary)}\n")

        print(f"\n{'+'*50}")
        print(f"SUCCESS: Pipeline complete!")
        print(f"Check the '{output_dir / 'final_summary.md'}' file for the final summary.")
        print(f"Check the '{output_dir / 'code_review.md'}' file for the full detailed review.")
        print(f"{'+'*50}")

    except Exception as e:
        print(f"\n[!] Pipeline failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
