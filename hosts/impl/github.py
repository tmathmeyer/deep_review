import asyncio
import os
import pathlib
import re
import shutil

from hosts.host import Host
from hosts.mixins.context import NoContext
from hosts.mixins.agents import Agentic
from hosts.mixins.summary import Summarizer
from hosts.mixins.console import ConsoleRenderer
from core.github_client import GitHubClient
from core.utils import save_file


class GitHub(NoContext, Agentic, Summarizer, ConsoleRenderer, Host):
  _REF_PATTERN = r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)"

  @classmethod
  def CreateFromRef(cls, code_ref: str) -> Host:
    if match := re.match(cls._REF_PATTERN, code_ref):
      return cls(*match.groups())
    return None

  def __init__(self, owner: str, repo: str, pr_id: str):
    self._owner = owner
    self._repo = repo
    self._pr_id = pr_id
    self._datadir = os.path.join("reviews", "github", owner, repo, pr_id)
    self._client = GitHubClient(owner, repo)

  def GetReviewDir(self) -> pathlib.Path:
    return pathlib.Path(self._datadir)

  def _save_commit_info(self, pr_data: dict):
    commit_info_content = (
      f"GitHub PR: {pr_data.get('html_url')}\n"
      f"Project: {self._owner}/{self._repo}\n"
      f"Author: {pr_data.get('user', {}).get('login')}\n\n"
      f"Title: {pr_data.get('title')}\n\n"
      f"{pr_data.get('body')}"
    )
    save_file(os.path.join(self._datadir, "commit_info"), commit_info_content)

  async def _save_diff(self, pr_data: dict):
    diff_url = pr_data.get("diff_url")
    if not diff_url:
      return
    diff_bytes = await self._client.fetch_diff(diff_url)
    save_file(os.path.join(self._datadir, "patch.diff"), diff_bytes)

  async def _extract_base_files(self, pr_data: dict):
    files_data = await self._client.fetch_pr_files(self._pr_id)
    semaphore = asyncio.Semaphore(5)

    async def _fetch_one_file(file_info):
      async with semaphore:
        fpath = file_info.get("filename")
        base_sha = pr_data.get("base", {}).get("sha")
        if not base_sha:
          return

        try:
          file_content = await self._client.fetch_raw_file(
            self._owner, self._repo, base_sha, fpath
          )
          if file_content:
            save_file(os.path.join(self._datadir, fpath), file_content)
        except Exception as e:
          print(f"Warning: Failed to fetch {fpath} from base {base_sha}: {e}")

    await asyncio.gather(*[_fetch_one_file(f) for f in files_data])

  async def FetchChange(self, tasks):
    if os.path.exists(self._datadir):
      shutil.rmtree(self._datadir)
    os.makedirs(self._datadir, exist_ok=True)

    # 1. Fetch PR Info
    pr_data = await self._client.fetch_pr_info(self._pr_id)

    self._save_commit_info(pr_data)

    # 2. Fetch Diff
    tasks.TrackJob("Fetch PR Diff", self._save_diff(pr_data))

    # 3. Fetch Files
    tasks.TrackJob("Fetch PR Files", self._extract_base_files(pr_data))
