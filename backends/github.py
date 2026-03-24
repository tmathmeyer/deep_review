import asyncio
import re
import urllib.request
import json
from pathlib import Path
from core.reviewer import Reviewer
from core.models import ChangeInfo
from vync import Vync
from core.utils import save_file


class GitHubReviewer(Reviewer):
    @classmethod
    def handles_target(cls, target: str) -> bool:
        return "github.com/" in target and "/pull/" in target

    async def fetch_change(
        self, target: str, output_dir: Path, vync_app: Vync
    ) -> ChangeInfo:
        # e.g. https://github.com/owner/repo/pull/123
        match = re.search(r"github\.com/([^/]+)/([^/]+)/pull/(\d+)", target)
        if not match:
            raise ValueError("Invalid GitHub PR URL")

        owner, repo, pr_id = match.groups()

        output_dir.mkdir(parents=True, exist_ok=True)

        # Use simple HTTP to get the PR info
        api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_id}"
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "deep-review",
            },
        )

        try:
            with urllib.request.urlopen(req) as response:
                pr_data = json.loads(response.read().decode())
        except Exception as e:
            raise Exception(f"Failed to fetch PR info: {e}")

        change_info = ChangeInfo(
            cl_id=pr_id,
            host="github.com",
            project=f"{owner}/{repo}",
            branch=pr_data.get("base", {}).get("ref", "UNKNOWN"),
            status=pr_data.get("state", "UNKNOWN"),
            author_name=pr_data.get("user", {}).get("login", "UNKNOWN"),
            created=pr_data.get("created_at", "UNKNOWN"),
            updated=pr_data.get("updated_at", "UNKNOWN"),
            subject=pr_data.get("title", "UNKNOWN"),
            message=pr_data.get("body", "UNKNOWN"),
            commit_url=pr_data.get("html_url", ""),
        )

        # Save commit info
        commit_info_content = f"GitHub PR: {change_info.commit_url}\nProject: {change_info.project}\nAuthor: {change_info.author_name}\n\nTitle: {change_info.subject}\n\n{change_info.message}"
        save_file(output_dir / "commit_info", commit_info_content)

        async def _fetch_diff():
            diff_url = pr_data.get("diff_url")
            if diff_url:
                diff_req = urllib.request.Request(
                    diff_url, headers={"User-Agent": "deep-review"}
                )
                with urllib.request.urlopen(diff_req) as diff_resp:
                    diff_bytes = diff_resp.read()
                    save_file(output_dir / "diff.patch", diff_bytes)

        vync_app.TrackJob("Fetch PR Diff", _fetch_diff())

        # For files, we fetch the /files endpoint
        async def _fetch_files():
            files_url = (
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_id}/files"
            )
            files_req = urllib.request.Request(
                files_url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": "deep-review",
                },
            )
            try:
                with urllib.request.urlopen(files_req) as files_resp:
                    files_data = json.loads(files_resp.read().decode())

                for file_info in files_data:
                    fpath = file_info.get("filename")
                    raw_url = file_info.get("raw_url")
                    if raw_url:
                        # Fetch original/raw file
                        file_req = urllib.request.Request(
                            raw_url, headers={"User-Agent": "deep-review"}
                        )
                        try:
                            with urllib.request.urlopen(file_req) as raw_resp:
                                save_file(output_dir / fpath, raw_resp.read())
                        except Exception:
                            pass
            except Exception:
                pass

        vync_app.TrackJob("Fetch PR Files", _fetch_files())
        vync_app.WaitAll()

        return change_info

    def get_reviewer_agents_dir(self) -> Path:
        base_dir = Path(__file__).parent.parent
        if self.mock:
            return base_dir / "mock_agents"
        return base_dir / "agents"
