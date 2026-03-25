"""
GitHub API client using aiohttp as an async context manager.
"""

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
    :param session: Optional external aiohttp.ClientSession.
    """
    self.owner = owner
    self.repo = repo
    self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
    self._session = session
    self._own_session = False

  async def __aenter__(self) -> "GitHubClient":
    if not self._session:
      self._session = aiohttp.ClientSession()
      self._own_session = True
    return self

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    if self._own_session and self._session:
      await self._session.close()
      self._session = None
      self._own_session = False

  async def _make_request(
    self, url: str, headers: Optional[Dict[str, str]] = None
  ) -> Any:
    """Helper to make a GET request and return JSON or raw bytes."""
    if self._session:
      return await self._do_request(self._session, url, headers)

    async with aiohttp.ClientSession() as session:
      return await self._do_request(session, url, headers)

  async def _do_request(
    self,
    session: aiohttp.ClientSession,
    url: str,
    headers: Optional[Dict[str, str]] = None,
  ) -> Any:
    default_headers = {
      "Accept": "application/vnd.github.v3+json",
      "User-Agent": "deep-review",
    }
    if headers:
      default_headers.update(headers)

    max_retries = 3
    for attempt in range(max_retries):
      try:
        async with session.get(url, headers=default_headers) as response:
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
      except (aiohttp.ClientError, asyncio.TimeoutError):
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
