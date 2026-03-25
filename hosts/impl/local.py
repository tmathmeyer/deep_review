import os
import pathlib
import re
import shutil
import subprocess

from hosts.host import Host
from hosts.mixins.context import NoContext
from hosts.mixins.agents import Agentic
from hosts.mixins.summary import Summarizer
from hosts.mixins.console import ConsoleRenderer


def _Git(*commands):
  proc = subprocess.run(["git", *commands], capture_output=True, text=True)
  if proc.returncode != 0:
    raise ValueError("GIT FAILURE")
  return proc.stdout.strip()


class Local(NoContext, Agentic, Summarizer, ConsoleRenderer, Host):
  _REF_PATTERN = r"local(:([a-fA-F0-9]+))?"
  _DATADIR = "reviews/local"

  @classmethod
  def CreateFromRef(cls, code_ref: str) -> Host:
    if match := re.match(cls._REF_PATTERN, code_ref):
      return cls(match.group(2))
    return None

  def __init__(self, commit_sha: str | None):
    self._sha = commit_sha

  def _get_archive_ref(self) -> str:
    if self._sha:
      return f"{self._sha}^"
    try:
      return _Git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    except:
      return "HEAD"

  def _save_diff(self, archive_ref: str, patch_path: str):
    if self._sha:
      diff = _Git("show", self._sha)
    else:
      diff = _Git("diff", archive_ref)
    with open(patch_path, "w") as f:
      f.write(diff)

  def _extract_base_files(self, archive_ref: str, base_dir: str):
    archive_proc = subprocess.Popen(
      ["git", "archive", archive_ref], stdout=subprocess.PIPE
    )
    subprocess.run(["tar", "-x", "-C", base_dir], stdin=archive_proc.stdout, check=True)
    archive_proc.wait()

  def GetReviewDir(self):
    return pathlib.Path(self._DATADIR)

  async def FetchChange(self, tasks):
    if os.path.exists(self._DATADIR):
      shutil.rmtree(self._DATADIR)
    os.makedirs(self._DATADIR, exist_ok=True)
    archive_ref = self._get_archive_ref()
    self._save_diff(archive_ref, os.path.join(self._DATADIR, "patch.diff"))
    self._extract_base_files(archive_ref, self._DATADIR)
