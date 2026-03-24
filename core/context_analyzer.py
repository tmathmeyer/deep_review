"""
Analyzes the codebase to find missing context using the LLM.
"""

import json
from pathlib import Path
from typing import Optional

from core.gemini_client import GeminiClient
from core.models import AnalysisResult
from core.utils import read_directory_context, save_file
from core.exceptions import ParseError


async def analyze_context(
    cl_dir: Path, gemini_client: GeminiClient, model_name: str, agents_dir: Path
) -> Optional[AnalysisResult]:
    """
    Reads the downloaded files and asks the LLM to identify the project and recommend
    additional context files needed for a full review.
    """
    document_text = read_directory_context(cl_dir)

    # Add agent prompts to context
    agent_texts = []
    if agents_dir.is_dir():
        for file_path in agents_dir.glob("*.md"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    agent_texts.append(
                        f"--- Code Review Agent: {file_path.name} ---\n{f.read()}\n"
                    )
            except Exception:
                pass

    if agent_texts:
        document_text += "\n" + "\n".join(agent_texts)

    if not document_text.strip():
        return None

    # Load prompt
    prompt_path = Path(__file__).parent.parent / "prompts" / "preview_change.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()
    except Exception:
        return None

    # We don't cache here because this is a one-off request
    response_text = await gemini_client.generate_content(
        model_name=model_name, prompt=prompt, document_text=document_text
    )

    if not response_text:
        return None

    # Parse JSON
    try:
        clean_text = response_text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]

        result_data = json.loads(clean_text)

        analysis = AnalysisResult(
            summary=result_data.get("summary", "Summary not provided."),
            extra_context_files=result_data.get("extra_context_files", []),
        )

        # Save output files
        save_file(cl_dir / "summary", analysis.summary)
        save_file(
            cl_dir / "extra_context_files",
            "\n".join(analysis.extra_context_files) + "\n",
        )

        return analysis

    except json.JSONDecodeError:
        return None
