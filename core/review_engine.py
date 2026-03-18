"""
Multi-threaded code review engine using Gemini Context Caching.
"""

import os
import time
import threading
import concurrent.futures
from pathlib import Path
from typing import List, Callable, Optional

from core.gemini_client import GeminiClient
from core.models import AgentReview
from core.utils import read_directory_context, save_file

COMMON_AGENT_INSTRUCTION = """
**CRITICAL INSTRUCTION:** You must analyze ONLY the code changes (the lines added or modified in the diff). Do NOT report issues, bugs, or improvements for existing code that was not modified in this changelist, even if it is provided in the context.
"""



from vync import Vync
import asyncio

def run_review(cl_dir: Path, gemini_client: GeminiClient, model_name: str, agents_dir: Path, vync_app: Vync) -> None:
    """
    Orchestrates the multi-agent code review process.
    Uses status_callback(agent_name, status, elapsed_time) to report progress to the UI.
    """
    # 1. Read the agents
    agents: List[tuple[str, str]] = []

    if agents_dir.is_dir():
        for file_path in agents_dir.glob("*.md"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    agent_prompt = f.read().strip()
                    agent_prompt += f"\n\n{COMMON_AGENT_INSTRUCTION}\n"
                    agents.append((file_path.stem, agent_prompt))
            except Exception as e:
                print(f"Failed to read agent prompt {file_path.name}: {e}")

    if not agents:
        print("Error: No agent prompts (.md files) found.")
        return

    # 2. Build the context
    document_text = read_directory_context(cl_dir)
    if not document_text.strip():
        print("Error: Context is empty.")
        return

    save_file(cl_dir / "full_context", document_text)

    # 3. Create cache
    cache_name = gemini_client.create_cached_content(model_name, document_text, ttl_seconds=600)

    if not cache_name:
        print("Caching failed or unsupported. Falling back to direct API requests...")

    results: List[AgentReview] = []

    for agent_name, prompt in agents:
        async def _run_agent(aname=agent_name, aprompt=prompt):
            try:
                # Wrap the gemini call since it is synchronous
                response_text = await asyncio.to_thread(
                    gemini_client.generate_content,
                    model_name,
                    aprompt,
                    document_text if not cache_name else None,
                    cache_name,
                    0.2, # temperature
                    300 # timeout
                )
                if response_text:
                    results.append(AgentReview(agent_name=aname, response_text=response_text, status="Done"))
                else:
                    results.append(AgentReview(agent_name=aname, response_text=None, status="Failed", error_message="Empty response"))
                    raise ValueError("Empty response")
            except Exception as e:
                if not any(r.agent_name == aname for r in results):
                    results.append(AgentReview(agent_name=aname, response_text=None, status="Failed", error_message=str(e)))
                raise

        vync_app.TrackJob(f"Agent: {agent_name}", _run_agent(), optional=True)
        
    vync_app.WaitAll()

    # 6. Cleanup cache
    if cache_name:
        gemini_client.delete_cached_content(cache_name)

    # 7. Aggregate and save results
    md_output = []

    # Sort results to be deterministic
    results.sort(key=lambda x: x.agent_name)

    for review in results:
        md_output.append(f"## Review by '{review.agent_name}'")
        if review.status == "Done" and review.response_text:
            md_output.append(review.response_text)
        else:
            md_output.append(f"*(Agent failed to generate review: {review.error_message})*")

    final_output = "\n\n---\n\n".join(md_output)
    out_file = cl_dir / "code_review.md"
    save_file(out_file, final_output)
