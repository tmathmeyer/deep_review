"""
Module for summarizing and deduplicating the results of multi-agent reviews.
"""

from pathlib import Path
from core.gemini_client import GeminiClient
from core.utils import save_file

def summarize_reviews(cl_dir: Path, gemini_client: GeminiClient, model_name: str) -> None:
    """
    Reads the diff.patch and code_review.md files, and uses the LLM to deduplicate
    and summarize the findings into a final, consolidated review.
    """
    diff_path = cl_dir / "diff.patch"
    review_path = cl_dir / "code_review.md"
    
    if not diff_path.exists() or not review_path.exists():
        print("Error: Missing diff.patch or code_review.md for summarization.")
        return

    # Load the raw files
    try:
        with open(diff_path, "r", encoding="utf-8") as f:
            diff_text = f.read()
        with open(review_path, "r", encoding="utf-8") as f:
            review_text = f.read()
    except Exception as e:
        print(f"Error reading files for summarization: {e}")
        return

    # Load prompt
    prompt_path = Path(__file__).parent.parent / "prompts" / "review_summary.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read().strip()
    except Exception as e:
        print(f"Error reading prompt file from {prompt_path}: {e}")
        return

    document_text = f"--- diff.patch ---\n{diff_text}\n\n--- code_review.md ---\n{review_text}\n"

    print(f"Sending summary request to Gemini API ({model_name})...")
    
    response_text, usage = gemini_client.generate_content(
        model_name=model_name,
        prompt=prompt,
        document_text=document_text
    )

    if not response_text:
        print("Failed to get review summary from Gemini API.")
        return

    # Save output
    out_file = cl_dir / "final_summary.md"
    save_file(out_file, response_text)
    print(f"Consolidated summary saved to {out_file}")
    
    # Optionally append usage stats for this final phase
    stats_md = f"\n\n---\n*Summarization Token Usage: {usage.prompt_tokens} Prompt | {usage.candidate_tokens} Generated | {usage.total_tokens} Total*\n"
    
    with open(out_file, "a", encoding="utf-8") as f:
        f.write(stats_md)
