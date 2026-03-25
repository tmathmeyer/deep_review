"""
Module for summarizing and deduplicating the results of multi-agent reviews.
"""

from pathlib import Path
from core.gemini_client import GeminiClient
from core.utils import save_file


async def summarize_reviews(
  cl_dir: Path, gemini_client: GeminiClient, model_name: str
) -> None:
  """
  Reads the diff.patch and code_review.md files, and uses the LLM to deduplicate
  and summarize the findings into a final, consolidated review.
  """
  diff_path = cl_dir / "patch.diff"
  review_path = cl_dir / "code_review.md"
  summary_path = cl_dir / "summary"
  commit_info_path = cl_dir / "commit_info"

  if not diff_path.exists() or not review_path.exists():
    raise FileNotFoundError(f"Missing required files in {cl_dir} for summarization.")

  diff_text = diff_path.read_text(encoding="utf-8")
  review_text = review_path.read_text(encoding="utf-8")

  summary_text = (
    summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
  )
  commit_info_text = (
    commit_info_path.read_text(encoding="utf-8") if commit_info_path.exists() else ""
  )

  prompt_path = Path(__file__).parent.parent / "prompts" / "review_summary.md"
  if not prompt_path.exists():
    raise FileNotFoundError(f"Prompt file not found at {prompt_path}")

  prompt = prompt_path.read_text(encoding="utf-8").strip()

  document_text = (
    f"--- commit_info ---\n{commit_info_text}\n\n"
    f"--- summary ---\n{summary_text}\n\n"
    f"--- code_review.md ---\n{review_text}\n\n"
    f"--- diff.patch ---\n{diff_text}\n"
  )

  response_text = await gemini_client.generate_content(
    model_name=model_name, prompt=prompt, document_text=document_text
  )

  if not response_text:
    raise ValueError("Failed to get review summary from Gemini API.")

  save_file(cl_dir / "final_summary.md", response_text)
