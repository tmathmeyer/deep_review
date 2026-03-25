"""
GitHub API client using aiohttp.
"""

import json
import asyncio
import aiohttp
from typing import Dict, Any, List, Optional


class GitHubClient:
  def __init__(
    self, owner: str, repo: str, session: Optional[aiohttp.ClientSession] = None
  ):
    """
    Initializes the client.
    :param owner: GitHub repo owner.
    :param repo: GitHub repo name.
    :param session: Optional aiohttp.ClientSession.
    """
    self.owner = owner
    self.repo = repo
    self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
    self._session = session

  def set_session(self, session: aiohttp.ClientSession):
    """Sets the active aiohttp session for this client."""
    self._session = session

  async def _make_request(
    self, url: str, headers: Optional[Dict[str, str]] = None
  ) -> Any:
    """Helper to make a GET request and return JSON or raw bytes."""
    if not self._session:
      raise RuntimeError("GitHubClient session is not set. Call set_session() first.")

    default_headers = {
      "Accept": "application/vnd.github.v3+json",
      "User-Agent": "deep-review",
    }
    if headers:
      default_headers.update(headers)

    max_retries = 3
    for attempt in range(max_retries):
      try:
        async with self._session.get(url, headers=default_headers) as response:
          if response.status == 200:
            if "application/json" in response.headers.get("Content-Type", ""):
              return await response.json()
            return await response.read()

          if (
            response.status == 429 or 500 <= response.status < 600
          ) and attempt < max_retries - 1:
            await asyncio.sleep(2**attempt)
            continue

          text = await response.text()
          raise Exception(f"GitHub API Error {response.status}: {text}")
      except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        if attempt < max_retries - 1:
          await asyncio.sleep(2**attempt)
          continue
        raise
    return None

  async def fetch_pr_info(self, pr_id: str) -> Dict[str, Any]:
    """Fetches metadata about a specific Pull Request."""
    url = f"{self.base_url}/pulls/{pr_id}"
    return await self._make_request(url)

  async def fetch_pr_files(self, pr_id: str) -> List[Dict[str, Any]]:
    """Lists files modified in a Pull Request."""
    url = f"{self.base_url}/pulls/{pr_id}/files"
    return await self._make_request(url)

  async def fetch_diff(self, diff_url: str) -> bytes:
    """Downloads the diff for a PR."""
    return await self._make_request(diff_url)

  async def fetch_raw_file(self, owner: str, repo: str, sha: str, path: str) -> bytes:
    """Downloads a raw file from GitHub."""
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/{path}"
    return await self._make_request(url)
