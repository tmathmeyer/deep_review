from pathlib import Path
from typing import List, Coroutine, Tuple

from core.gemini_client import GeminiClient
from core.utils import read_directory_context, save_file


COMMON_AGENT_INSTRUCTION = """
**CRITICAL INSTRUCTION:** You must analyze ONLY the code changes (the lines added or modified in the diff). Do NOT report issues, bugs, or improvements for existing code that was not modified in this changelist, even if it is provided in the context.
"""


async def get_reviews(
  cl_dir: Path,
  gemini_client: GeminiClient,
  model_name: str,
  agents_dir: Path,
) -> List[Coroutine]:
  agents = _load_agents(agents_dir)

  if not agents:
    raise ValueError("No agent prompts (.md files) found.")

  document_text = read_directory_context(cl_dir)
  if not document_text.strip():
    raise ValueError("Context is empty.")

  save_file(cl_dir / "full_context", document_text)

  cache_name = await gemini_client.create_cached_content(
    model_name, document_text, ttl_seconds=600
  )

  return [
    (
      agent_name,
      _run_agent_review(
        agent_name,
        prompt,
        gemini_client,
        model_name,
        document_text,
        cache_name,
        cl_dir / "REVIEWS",
      ),
    )
    for agent_name, prompt in agents
  ]


def _load_agents(agents_dir: Path) -> List[Tuple[str, str]]:
  agents = []
  if agents_dir.is_dir():
    for file_path in agents_dir.glob("*.md"):
      with open(file_path, "r", encoding="utf-8") as f:
        prompt = f.read().strip()
        full_prompt = f"{prompt}\n\n{COMMON_AGENT_INSTRUCTION}\n"
        agents.append((file_path.stem, full_prompt))
  return agents


async def _run_agent_review(
  agent_name: str,
  prompt: str,
  gemini_client: GeminiClient,
  model_name: str,
  document_text: str,
  cache_name: str | None,
  agents_out_dir: Path,
):
  response_text = await gemini_client.generate_content(
    model_name,
    prompt,
    document_text if not cache_name else None,
    cache_name,
    0.2,
    300,
  )
  file_path = agents_out_dir / f"{agent_name}.md"

  if response_text:
    save_file(file_path, response_text)
  else:
    save_file(
      file_path,
      "*(Agent failed to generate review: Empty response from Gemini)*",
    )
