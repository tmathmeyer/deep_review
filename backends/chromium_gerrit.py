from pathlib import Path
from core.reviewer import Reviewer
from core.models import ChangeInfo
from vync import Vync
from core.change_fetcher import fetch_change, parse_gerrit_url


class ChromiumGerritReviewer(Reviewer):
    @classmethod
    def handles_target(cls, target: str) -> bool:
        try:
            parse_gerrit_url(target)
            return True
        except ValueError:
            return False

    async def fetch_change(
        self, target: str, output_dir: Path, vync_app: Vync
    ) -> ChangeInfo:
        # fetch_change is currently synchronous, but wait, the inner tasks use vync.
        # we can just call it
        return fetch_change(target, output_dir, vync_app)

    def get_reviewer_agents_dir(self) -> Path:
        base_dir = Path(__file__).parent.parent
        if self.mock:
            return base_dir / "mock_agents"
        return base_dir / "agents"
