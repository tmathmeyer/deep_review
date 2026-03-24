"""
Multi-threaded code review engine using Gemini Context Caching.
"""

from pathlib import Path
from typing import List

from core.gemini_client import GeminiClient
from core.models import AgentReview
from core.utils import read_directory_context, save_file
from vync import Vync

COMMON_AGENT_INSTRUCTION = """
**CRITICAL INSTRUCTION:** You must analyze ONLY the code changes (the lines added or modified in the diff). Do NOT report issues, bugs, or improvements for existing code that was not modified in this changelist, even if it is provided in the context.
"""


async def run_review(
    cl_dir: Path,
    gemini_client: GeminiClient,
    model_name: str,
    agents_dir: Path,
    vync_app: Vync,
) -> None:
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
                print(f"Error reading agent prompt {file_path.name}: {e}")
                # We don't want to silently fail if an agent is unreadable

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
    cache_name = await gemini_client.create_cached_content(
        model_name, document_text, ttl_seconds=600
    )

    if not cache_name:
        print("Caching failed or unsupported. Falling back to direct API requests...")

    results: List[AgentReview] = []

    try:
        for agent_name, prompt in agents:

            async def _run_agent(aname=agent_name, aprompt=prompt):
                try:
                    # Wrap the gemini call since it is synchronous
                    response_text = await gemini_client.generate_content(
                        model_name,
                        aprompt,
                        document_text if not cache_name else None,
                        cache_name,
                        0.2,  # temperature
                        300,  # timeout
                    )
                    if response_text:
                        results.append(
                            AgentReview(
                                agent_name=aname, response_text=response_text, status="Done"
                            )
                        )
                    else:
                        error_msg = "Empty response from Gemini"
                        results.append(
                            AgentReview(
                                agent_name=aname,
                                response_text=None,
                                status="Failed",
                                error_message=error_msg,
                            )
                        )
                        raise ValueError(error_msg)
                except Exception as e:
                    if not any(r.agent_name == aname for r in results):
                        results.append(
                            AgentReview(
                                agent_name=aname,
                                response_text=None,
                                status="Failed",
                                error_message=str(e),
                            )
                        )
                    raise

            vync_app.TrackJob(f"Agent: {agent_name}", _run_agent(), optional=True)

        await vync_app.await_all()

    finally:
        # 6. Cleanup cache
        if cache_name:
            try:
                await gemini_client.delete_cached_content(cache_name)
            except Exception as e:
                print(f"Warning: Failed to delete cache {cache_name}: {e}")

    # 7. Aggregate and save results
    md_output = []

    # Sort results to be deterministic
    results.sort(key=lambda x: x.agent_name)

    for review in results:
        md_output.append(f"## Review by '{review.agent_name}'")
        if review.status == "Done" and review.response_text:
            md_output.append(review.response_text)
        else:
            md_output.append(
                f"*(Agent failed to generate review: {review.error_message})*"
            )

    final_output = "\n\n---\n\n".join(md_output)
    out_file = cl_dir / "code_review.md"
    save_file(out_file, final_output)
