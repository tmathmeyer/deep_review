from core.review_summarizer import summarize_reviews
from core.utils import save_file


class Summarizer:
    def aggregate_reviews(self, review_dir: Path) -> str:
        agents_path = review_dir / "REVIEWS"

        if not agents_path.is_dir():
            return ""

        md_output = []
        agent_files = sorted(agents_path.glob("*.md"))

        for file_path in agent_files:
            agent_name = file_path.stem
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

            md_output.append(f"## Review by '{agent_name}'")
            if content:
                md_output.append(content)
            else:
                md_output.append("*(Agent failed to generate review: Empty file)*")

        final_output = "\n\n---\n\n".join(md_output)
        save_file(review_dir / "code_review.md", final_output)

        return final_output

    async def SummarizeReviews(self, tasks):
        self.aggregate_reviews(self.GetReviewDir())
        await summarize_reviews(self.GetReviewDir(), self._gemini, self._model)
