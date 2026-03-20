import asyncio
import subprocess
from pathlib import Path
from core.reviewer import Reviewer
from core.models import ChangeInfo
from vync import Vync
from core.utils import save_file

class LocalReviewer(Reviewer):
    @classmethod
    def handles_target(cls, target: str) -> bool:
        return target.lower() == "local"

    async def fetch_change(self, target: str, output_dir: Path, vync_app: Vync) -> ChangeInfo:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # We will track jobs for diff and files using vync
        change_info = ChangeInfo(
            cl_id="local",
            host="localhost",
            subject="Local Change",
            message="Diff from local repository",
            author_name="Local User"
        )

        async def _fetch_diff():
            # Get the diff between HEAD and working directory or upstream.
            # We'll just diff against HEAD for local unstaged/staged changes as a simple fallback,
            # or upstream if available. Let's just do `git diff HEAD` for simplicity of "local changes".
            proc = await asyncio.create_subprocess_shell(
                "git diff HEAD", 
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            save_file(output_dir / "diff.patch", stdout)

        vync_app.TrackJob("Fetch Local Diff", _fetch_diff())

        # Also get modified files to copy them to output_dir
        async def _fetch_files():
            proc = await asyncio.create_subprocess_shell(
                "git diff HEAD --name-only", 
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            files = stdout.decode().strip().split("\n")
            
            for f in files:
                if not f: continue
                # Copy current file state if it exists
                f_path = Path(f)
                if f_path.exists() and f_path.is_file():
                    content = f_path.read_bytes()
                    save_file(output_dir / f, content)

        vync_app.TrackJob("Fetch Local Files", _fetch_files())
        vync_app.WaitAll()

        # Save a fake commit info
        save_file(output_dir / "commit_info", "Local Changes Review\n")

        return change_info

    def get_reviewer_agents_dir(self) -> Path:
        base_dir = Path(__file__).parent.parent
        if self.mock:
            return base_dir / "mock_agents"
        return base_dir / "agents"
