
from core.render import render_markdown


class ConsoleRenderer:
    async def RenderReview(self, tasks):
        file = self.GetReviewDir() / "final_summary.md"
        with open(file, 'r') as f:
            print(render_markdown(f.read()))
