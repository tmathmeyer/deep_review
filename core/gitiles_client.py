"""
Gitiles API client for fetching repository trees and files.
"""

import json
import asyncio
import urllib.parse
import aiohttp
from typing import Dict, Any, Optional

from core.exceptions import GerritAPIError
from vync import Vync


class GitilesClient:
  def __init__(self, host: str, session: Optional[aiohttp.ClientSession] = None):
    """
    Initializes the client.
    :param host: e.g., 'chromium.googlesource.com'
    :param session: Optional external aiohttp.ClientSession.
    """
    self.host = host
    self._session = session
    self._own_session = False

  async def __aenter__(self) -> "GitilesClient":
    if not self._session:
      self._session = aiohttp.ClientSession()
      self._own_session = True
    return self

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    if self._own_session and self._session:
      await self._session.close()
      self._session = None
      self._own_session = False

  async def fetch_directory(
    self,
    project: str,
    commit_id: str,
    dir_path: str,
    gitiles_commit_url: str = "",
    recursive: bool = False,
  ) -> Dict[str, Any]:
    """
    Fetches the contents of a directory using the Gitiles REST API.
    """
    if self._session:
      return await self._do_gitiles_request(
        self._session, project, commit_id, dir_path, gitiles_commit_url, recursive
      )

    async with aiohttp.ClientSession() as session:
      return await self._do_gitiles_request(
        session, project, commit_id, dir_path, gitiles_commit_url, recursive
      )

  async def _do_gitiles_request(
    self,
    session: aiohttp.ClientSession,
    project: str,
    commit_id: str,
    dir_path: str,
    gitiles_commit_url: str = "",
    recursive: bool = False,
  ) -> Dict[str, Any]:
    encoded_dir = urllib.parse.quote(dir_path, safe="") if dir_path else ""
    path_suffix = f"/{encoded_dir}/" if encoded_dir else "/"

    if gitiles_commit_url:
      url = f"{gitiles_commit_url.rstrip('/')}{path_suffix}?format=JSON"
    else:
      encoded_project = urllib.parse.quote(project, safe="")
      url = (
        f"https://{self.host}/{encoded_project}/+/{commit_id}{path_suffix}?format=JSON"
      )

    if recursive:
      url += "&recursive=1"

    max_retries = 5
    for attempt in range(max_retries):
      try:
        async with session.get(url) as response:
          if response.status == 200:
            raw_bytes = await response.read()
            data_str = raw_bytes.decode("utf-8")
            if data_str.startswith(")]}'"):
              data_str = data_str[4:]
            return json.loads(data_str)

          if response.status == 404:
            return {"entries": []}

          if (
            response.status == 429 or 500 <= response.status < 600
          ) and attempt < max_retries - 1:
            await asyncio.sleep(2**attempt)
            continue

          raise GerritAPIError(
            f"HTTP Error {response.status} fetching {url}",
            status_code=response.status,
            details=await response.text(),
          )
      except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        if attempt < max_retries - 1:
          await asyncio.sleep(2**attempt)
          continue
        raise GerritAPIError(f"Network error fetching {url}: {e}")
      except Exception as e:
        raise GerritAPIError(f"Unexpected error fetching {url}: {e}")

  async def fetch_project_tree(
    self,
    tasks: Vync,
    project: str,
    commit_id: str,
    modified_files: list[str],
    gitiles_link: str = "",
  ) -> str:
    """Fetches directory listings for folders containing modified files and returns a tree string."""
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

    async def _fetch_shallow_dir(dp):
      try:
        dir_data = await self.fetch_directory(
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
      except Exception:
        pass

    job_futures = []
    for dp in sorted(list(shallow_dirs)):
      job_futures.append(
        tasks.TrackJob(f"Gitiles: {dp or '/'}", _fetch_shallow_dir(dp))
      )

    await tasks.JoinJobs(job_futures)

    if not tree_files:
      return ""

    return (
      "Project files near the changed files:\n\n"
      + "\n".join(sorted(list(tree_files)))
      + "\n"
    )
