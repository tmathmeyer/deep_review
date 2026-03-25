"""
Gerrit API client using aiohttp as an async context manager.
"""

import json
import asyncio
import base64
import urllib.parse
import aiohttp
from typing import Dict, Any, Optional

from core.exceptions import GerritAPIError, ParseError


class GerritClient:
  def __init__(self, host: str, session: Optional[aiohttp.ClientSession] = None):
    """
    Initializes the client.
    :param host: e.g., 'chromium-review.googlesource.com'
    :param session: Optional external aiohttp.ClientSession.
    """
    self.host = host
    self.base_url = f"https://{self.host}/changes"
    self._session = session
    self._own_session = False

  async def __aenter__(self) -> "GerritClient":
    if not self._session:
      self._session = aiohttp.ClientSession()
      self._own_session = True
    return self

  async def __aexit__(self, exc_type, exc_val, exc_tb):
    if self._own_session and self._session:
      await self._session.close()
      self._session = None
      self._own_session = False

  async def _make_request(self, endpoint: str) -> bytes:
    """Helper to make a raw GET request to the Gerrit API."""
    if self._session:
      return await self._do_request(self._session, endpoint)
    
    async with aiohttp.ClientSession() as session:
      return await self._do_request(session, endpoint)

  async def _do_request(self, session: aiohttp.ClientSession, endpoint: str) -> bytes:
    url = f"{self.base_url}/{endpoint}"

    max_retries = 5
    for attempt in range(max_retries):
      try:
        async with session.get(url) as response:
          if response.status == 200:
            return await response.read()

          # Retry on 429 (Too Many Requests) or 5xx (Server Errors)
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
        # Retry on network-level errors
        if attempt < max_retries - 1:
          await asyncio.sleep(2**attempt)
          continue
        raise GerritAPIError(f"Network error fetching {url}: {e}")
      except Exception as e:
        raise GerritAPIError(f"Unexpected error fetching {url}: {e}")

  async def get_json(self, endpoint: str) -> Dict[str, Any]:
    """
    Fetches data from Gerrit and parses the JSON.
    Automatically strips the XSSI magic string `)]}'`.
    """
    raw_bytes = await self._make_request(endpoint)
    try:
      data_str = raw_bytes.decode("utf-8")
      if data_str.startswith(")]}'"):
        data_str = data_str[4:]
      return json.loads(data_str)
    except json.JSONDecodeError as e:
      raise ParseError(f"Failed to parse JSON from Gerrit: {e}")
    except Exception as e:
      raise ParseError(f"Failed to decode Gerrit response: {e}")

  async def get_base64_file(self, endpoint: str) -> bytes:
    """
    Fetches a base64 encoded response from Gerrit and decodes it to raw bytes.
    """
    encoded_data = await self._make_request(endpoint)
    try:
      return base64.b64decode(encoded_data)
    except Exception as e:
      raise ParseError(f"Failed to decode base64 data from Gerrit: {e}")

  async def fetch_change_info(self, change_id: str) -> Dict[str, Any]:
    """Fetches metadata about a specific CL."""
    endpoint = f"{change_id}?o=CURRENT_REVISION&o=CURRENT_COMMIT&o=WEB_LINKS"
    return await self.get_json(endpoint)

  async def fetch_changed_files(self, change_id: str) -> Dict[str, Any]:
    """Returns the list of files modified in the current revision."""
    endpoint = f"{change_id}/revisions/current/files/"
    return await self.get_json(endpoint)

  async def fetch_patch_diff(self, change_id: str, context_lines: int = 20) -> bytes:
    """Downloads the full unified diff for the current revision."""
    endpoint = f"{change_id}/revisions/current/patch?context={context_lines}"
    return await self.get_base64_file(endpoint)

  async def fetch_original_file(self, change_id: str, file_path: str) -> bytes:
    """Downloads the original file content from the base commit (parent=1)."""
    encoded_path = urllib.parse.quote(file_path, safe="")
    endpoint = f"{change_id}/revisions/current/files/{encoded_path}/content?parent=1"
    return await self.get_base64_file(endpoint)

  async def fetch_gitiles_directory(
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
      return await self._do_gitiles_request(self._session, project, commit_id, dir_path, gitiles_commit_url, recursive)
    
    async with aiohttp.ClientSession() as session:
      return await self._do_gitiles_request(session, project, commit_id, dir_path, gitiles_commit_url, recursive)

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
      url = f"https://{self.host}/plugins/gitiles/{encoded_project}/+/{commit_id}{path_suffix}?format=JSON"

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
