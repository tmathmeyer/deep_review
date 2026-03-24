import asyncio
import json
import os
import pathlib
import re
import shutil
import urllib.request

from hosts.host import Host
from hosts.mixins.context import NoContext
from hosts.mixins.agents import Agentic
from hosts.mixins.summary import Summarizer
from hosts.mixins.console import ConsoleRenderer
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
        diff_req = urllib.request.Request(
            diff_url, headers={"User-Agent": "deep-review"}
        )

        def _do_fetch_diff():
            with urllib.request.urlopen(diff_req, timeout=30.0) as diff_resp:
                return diff_resp.read()

        diff_bytes = await asyncio.to_thread(_do_fetch_diff)
        save_file(os.path.join(self._datadir, "patch.diff"), diff_bytes)

    async def _extract_base_files(self, pr_data: dict):
        # In GitHub, we fetch modified files at their base revision if possible.
        # For simplicity and to match previous behavior, we fetch them as they are in the PR.
        # Ideally, we should fetch from the base commit.
        files_url = f"https://api.github.com/repos/{self._owner}/{self._repo}/pulls/{self._pr_id}/files"
        files_req = urllib.request.Request(
            files_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "deep-review",
            },
        )

        def _do_fetch_files_list():
            with urllib.request.urlopen(files_req, timeout=30.0) as files_resp:
                return json.loads(files_resp.read().decode())

        files_data = await asyncio.to_thread(_do_fetch_files_list)
        semaphore = asyncio.Semaphore(5)

        async def _fetch_one_file(file_info):
            async with semaphore:
                fpath = file_info.get("filename")
                # To get the base version, we'd need to fetch from pr_data['base']['sha']
                # But here we use raw_url which is the PR version. 
                # local.py uses the base version. 
                # Let's try to get the base version for more consistency.
                base_sha = pr_data.get("base", {}).get("sha")
                raw_url = f"https://raw.githubusercontent.com/{self._owner}/{self._repo}/{base_sha}/{fpath}"
                
                if raw_url:
                    file_req = urllib.request.Request(
                        raw_url, headers={"User-Agent": "deep-review"}
                    )
                    def _do_fetch_one():
                        try:
                            with urllib.request.urlopen(file_req, timeout=30.0) as raw_resp:
                                return raw_resp.read()
                        except:
                            return None

                    file_content = await asyncio.to_thread(_do_fetch_one)
                    if file_content:
                        save_file(os.path.join(self._datadir, fpath), file_content)

        await asyncio.gather(*[_fetch_one_file(f) for f in files_data])

    async def FetchChange(self, tasks):
        if os.path.exists(self._datadir):
            shutil.rmtree(self._datadir)
        os.makedirs(self._datadir, exist_ok=True)

        # 1. Fetch PR Info
        api_url = f"https://api.github.com/repos/{self._owner}/{self._repo}/pulls/{self._pr_id}"
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "deep-review",
            },
        )

        def _fetch_pr_info():
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())

        pr_data = await asyncio.to_thread(_fetch_pr_info)

        self._save_commit_info(pr_data)

        # 2. Fetch Diff
        tasks.TrackJob("Fetch PR Diff", self._save_diff(pr_data))

        # 3. Fetch Files
        tasks.TrackJob("Fetch PR Files", self._extract_base_files(pr_data))
        
        await tasks.await_all()
