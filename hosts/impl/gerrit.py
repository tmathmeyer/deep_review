import asyncio
import os
import pathlib
import re
import shutil

from hosts.host import Host
from hosts.mixins.context import DeducesContext
from hosts.mixins.agents import Agentic
from hosts.mixins.summary import Summarizer
from hosts.mixins.console import ConsoleRenderer
from core.gerrit_client import GerritClient
from core.utils import save_file


class Gerrit(DeducesContext, Agentic, Summarizer, ConsoleRenderer, Host):
    _REF_PATTERN = r"https://([^/]+)/.*/\+/(\d+)"

    @classmethod
    def CreateFromRef(cls, code_ref: str) -> Host:
        if match := re.match(cls._REF_PATTERN, code_ref):
            return cls(match.group(1), match.group(2))
        if code_ref.isdigit():
            return cls("chromium-review.googlesource.com", code_ref)
        return None

    def __init__(self, host: str, change_id: str):
        self._host = host
        self._change_id = change_id
        self._datadir = os.path.join("reviews", "gerrit", host, change_id)
        self._client = GerritClient(host)

    def GetReviewDir(self) -> pathlib.Path:
        return pathlib.Path(self._datadir)

    def _save_commit_info(self, info_json: dict, numeric_id: str, current_rev: str):
        project = info_json.get("project", "")
        commit_url = f"https://{self._host}/c/{project}/+/{numeric_id}"
        
        gitiles_link = ""
        patch_set_num = "UNKNOWN"
        subject = "UNKNOWN"
        message = "UNKNOWN"
        author_name = "UNKNOWN"
        author_email = "UNKNOWN"

        if current_rev:
            revision_data = info_json.get("revisions", {}).get(current_rev, {})
            patch_set_num = revision_data.get("_number", "UNKNOWN")
            commit_data = revision_data.get("commit", {})
            subject = commit_data.get("subject", "UNKNOWN")
            message = commit_data.get("message", "UNKNOWN")
            author_data = commit_data.get("author", {})
            author_name = author_data.get("name", "UNKNOWN")
            author_email = author_data.get("email", "UNKNOWN")

            for link in commit_data.get("web_links", []):
                if link.get("name") == "Gitiles":
                    gitiles_link = link.get("url")
                    break

        commit_info_content = (
            f"Commit URL: {commit_url}\n"
            f"Gitiles Link: {gitiles_link if gitiles_link else 'Not available'}\n"
            f"Project: {project}\n"
            f"Branch: {info_json.get('branch', 'UNKNOWN')}\n"
            f"Status: {info_json.get('status', 'UNKNOWN')}\n"
            f"Patch Set: {patch_set_num}\n"
            f"Author: {author_name} <{author_email}>\n"
            f"Created: {info_json.get('created', 'UNKNOWN')}\n"
            f"Updated: {info_json.get('updated', 'UNKNOWN')}\n"
            f"\nSubject: {subject}\n"
            f"\nCommit Message:\n{message}\n"
        )
        save_file(self.GetReviewDir() / "commit_info", commit_info_content)
        return project, gitiles_link, current_rev

    async def _save_diff(self):
        patch_bytes = await asyncio.to_thread(self._client.fetch_patch_diff, self._change_id, 20)
        save_file(self.GetReviewDir() / "patch.diff", patch_bytes)

    async def _extract_base_files(self, project, current_rev, gitiles_link):
        files_data = await asyncio.to_thread(self._client.fetch_changed_files, self._change_id)
        modified_files = []
        semaphore = asyncio.Semaphore(10)

        async def _fetch_orig(fp):
            async with semaphore:
                try:
                    original_bytes = await asyncio.to_thread(
                        self._client.fetch_original_file, self._change_id, fp
                    )
                    save_file(self.GetReviewDir() / fp, original_bytes)
                except Exception as e:
                    print(f"Error fetching original file {fp}: {e}")

        fetch_tasks = []
        for file_path in files_data.keys():
            if file_path == "/COMMIT_MSG":
                continue
            modified_files.append(file_path)
            fetch_tasks.append(_fetch_orig(file_path))
        
        await asyncio.gather(*fetch_tasks)
        return modified_files

    async def _fetch_project_tree(self, project, current_rev, gitiles_link, modified_files):
        deep_dirs = set()
        for file_path in modified_files:
            parts = file_path.split("/")
            if len(parts) > 1:
                deep_dirs.add("/".join(parts[:-1]))

        shallow_dirs = set([""])
        for dir_path in deep_dirs:
            parts = dir_path.split("/")
            for i in range(1, len(parts)):
                shallow_dirs.add("/".join(parts[:i]))

        tree_files = set()
        commit_id = current_rev if current_rev else "HEAD"
        semaphore = asyncio.Semaphore(10)

        async def _fetch_shallow_dir(dp):
            async with semaphore:
                try:
                    dir_data = await asyncio.to_thread(
                        self._client.fetch_gitiles_directory,
                        project,
                        commit_id,
                        dp,
                        gitiles_link,
                    )
                    entries = dir_data.get("entries", [])
                    for entry in entries:
                        if entry.get("type") == "blob":
                            file_name = entry.get("name")
                            full_path = f"{dp}/{file_name}" if dp else file_name
                            tree_files.add(full_path)
                except:
                    pass

        dir_tasks = [(_fetch_shallow_dir(dp)) for dp in shallow_dirs]
        await asyncio.gather(*dir_tasks)

        if tree_files:
            tree_content = (
                "Project files near the changed files:\n\n"
                + "\n".join(sorted(list(tree_files)))
                + "\n"
            )
            save_file(self.GetReviewDir() / "project_tree", tree_content)

    async def FetchChange(self, tasks):
        if os.path.exists(self._datadir):
            shutil.rmtree(self._datadir)
        os.makedirs(self._datadir, exist_ok=True)

        # 1. Fetch Change Info
        info_json = await asyncio.to_thread(self._client.fetch_change_info, self._change_id)
        numeric_id = info_json.get("_number", self._change_id)
        current_rev = info_json.get("current_revision", "")
        
        project, gitiles_link, current_rev = self._save_commit_info(info_json, numeric_id, current_rev)

        # 2. Fetch Diff
        tasks.TrackJob("Fetch Diff", self._save_diff())

        # 3. Fetch Files and Tree
        async def _fetch_files_and_tree():
            modified_files = await self._extract_base_files(project, current_rev, gitiles_link)
            await self._fetch_project_tree(project, current_rev, gitiles_link, modified_files)

        tasks.TrackJob("Fetch Files and Tree", _fetch_files_and_tree())
