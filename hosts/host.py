from abc import ABC, abstractmethod
from pathlib import Path


MOCK_MODEL = "gemini-3.1-flash-lite-preview"


class Host(ABC):
  def ConfigureModel(self, args, gemini_client):
    self._model = MOCK_MODEL if args.mock else args.model
    self._gemini = gemini_client
    self._args = args

  def Steps(self):
    return [
      ("Fetch Change", self.FetchChange),
      ("Expand Context", self.FindAdditionalContext),
      ("Multi-Agent Review", self.MultiAgentReview),
      ("Summarize Reviews", self.SummarizeReviews),
      ("Render Review", self.RenderReview),
    ]

  @classmethod
  @abstractmethod
  def CreateFromRef(cls, code_ref: str) -> Host:
    pass

  @abstractmethod
  def GetReviewDir(self) -> Path:
    pass

  @abstractmethod
  async def FetchChange(self, tasks):
    pass

  @abstractmethod
  async def FindAdditionalContext(self, tasks):
    pass

  @abstractmethod
  async def MultiAgentReview(self, tasks):
    pass

  @abstractmethod
  async def SummarizeReviews(self, tasks):
    pass

  @abstractmethod
  async def RenderReview(self, tasks):
    pass
