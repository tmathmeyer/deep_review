from abc import ABC, abstractmethod
from pathlib import Path
from core.models import ChangeInfo
from core.gemini_client import GeminiClient
from vync import Vync
from core.context_analyzer import analyze_context
from core.review_engine import run_review
from core.review_summarizer import summarize_reviews
from core.render import render_markdown


class Reviewer(ABC):
    def __init__(self, gemini_client: GeminiClient, model_name: str, mock: bool):
        self.gemini_client = gemini_client
        self.model_name = model_name
        self.mock = mock

    @classmethod
    @abstractmethod
    def handles_target(cls, target: str) -> bool:
        pass

    @abstractmethod
    async def fetch_change(
        self, target: str, output_dir: Path, vync_app: Vync
    ) -> ChangeInfo:
        pass

    async def deduce_more_context(
        self, change_info: ChangeInfo, output_dir: Path, vync_app: Vync
    ) -> None:
        pass

    async def perform_analysis(
        self, change_info: ChangeInfo, output_dir: Path, vync_app: Vync
    ) -> dict:
        agents_dir = self.get_reviewer_agents_dir()
        return await analyze_context(
            output_dir, self.gemini_client, self.model_name, agents_dir
        )

    @abstractmethod
    def get_reviewer_agents_dir(self) -> Path:
        pass

    async def run_review_agents(
        self, change_info: ChangeInfo, output_dir: Path, vync_app: Vync
    ) -> None:
        agents_dir = self.get_reviewer_agents_dir()
        await run_review(
            output_dir, self.gemini_client, self.model_name, agents_dir, vync_app
        )

    async def coalesce_reviews(
        self, change_info: ChangeInfo, output_dir: Path, vync_app: Vync
    ) -> str:
        return await summarize_reviews(output_dir, self.gemini_client, self.model_name)

    def render_reviews(self, summary: str, output_dir: Path) -> str:
        return render_markdown(summary)
