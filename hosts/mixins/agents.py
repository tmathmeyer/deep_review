import pathlib

from core.review_engine import get_reviews


class Agentic:
    async def MultiAgentReview(self, tasks):
        base_dir = pathlib.Path(__file__).parent.parent.parent
        if self._args.mock:
            agents = base_dir / "mock_agents"
        else:
            agents = base_dir / "agents"
        reviews = await get_reviews(
            self.GetReviewDir(), self._gemini, self._model, agents
        )
        for name, reviewer in reviews:
            tasks.TrackJob(name, reviewer)
