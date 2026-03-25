"""
Fetches extra context files from Gerrit.
"""

from pathlib import Path

from core.gerrit_client import GerritClient
from core.models import AnalysisResult, ChangeInfo
from core.utils import save_file

from vync import Vync
import asyncio


async def fetch_extra_context(
  cl_dir: Path, change_info: ChangeInfo, analysis: AnalysisResult, vync_app: Vync
) -> None:
  """
  Downloads the extra files identified by the analysis module using the Gerrit API.
  """
  if not analysis.extra_context_files:
    print("No extra context files to download.")
    return

  client = GerritClient(change_info.host)

  # Limit concurrency
  semaphore = asyncio.Semaphore(20)

  for file_path in analysis.extra_context_files:

    async def _fetch_extra(fp=file_path):
      async with semaphore:
        try:
          original_bytes = await asyncio.to_thread(
            client.fetch_original_file, change_info.cl_id, fp
          )
          local_file_path = cl_dir / fp
          save_file(local_file_path, original_bytes)
        except Exception as e:
          raise ValueError(f"Warning: Failed to fetch extra context file {fp}: {e}")

    vync_app.TrackJob(f"Fetch Extra: {file_path}", _fetch_extra())
