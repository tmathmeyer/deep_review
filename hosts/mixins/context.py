import pathlib
from core.context_analyzer import analyze_context
from core.extra_context_fetcher import fetch_extra_context
from core.models import ChangeInfo


class NoContext:
  async def FindAdditionalContext(self, tasks):
    pass


class DeducesContext:
  async def FindAdditionalContext(self, tasks):
    base_dir = pathlib.Path(__file__).parent.parent.parent
    if self._args.mock:
      agents = base_dir / "mock_agents"
    else:
      agents = base_dir / "agents"

    analysis = await analyze_context(
      self.GetReviewDir(), self._gemini, self._model, agents
    )
    if analysis and analysis.extra_context_files:
      # Reconstruct ChangeInfo for fetch_extra_context
      # This assumes the host has _host and _change_id (like Gerrit)
      change_info = ChangeInfo(
        cl_id=getattr(self, "_change_id", ""),
        host=getattr(self, "_host", ""),
      )
      await fetch_extra_context(self.GetReviewDir(), change_info, analysis, tasks)
