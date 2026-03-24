import asyncio
import subprocess
import shutil
import shlex
from pathlib import Path
from typing import Optional, Union, Any, List
from core.reviewer import Reviewer
from core.models import ChangeInfo
from vync import Vync
from core.utils import save_file


class LocalReviewer(Reviewer):
    @classmethod
    def handles_target(cls, target: str) -> bool:
        return target.lower() == "local" or target.lower().startswith("local:")

    async def _run_git_command(
        self,
        *args: str,
        cwd: Optional[Path] = None,
        input_data: Optional[bytes] = None,
        stdout: Any = asyncio.subprocess.PIPE,
        stderr: Any = asyncio.subprocess.PIPE,
        timeout: float = 30.0,
        return_bytes: bool = False,
    ) -> Union[str, bytes]:
        """Helper to run git commands with proper timeout and error handling."""
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE if input_data is not None else None,
                stdout=stdout,
                stderr=stderr,
            )
            
            # communicate() returns (stdout_data, stderr_data) if pipes are used.
            # If stdout/stderr are redirected to files, those values will be None.
            stdout_data, stderr_data = await asyncio.wait_for(
                proc.communicate(input=input_data), timeout=timeout
            )

            if proc.returncode != 0:
                stderr_str = stderr_data.decode(errors="replace") if stderr_data else ""
                raise subprocess.CalledProcessError(
                    proc.returncode,
                    f"git {' '.join(args)}",
                    output=stdout_data,
                    stderr=stderr_str,
                )

            if return_bytes:
                return stdout_data or b""
            return (stdout_data or b"").decode(errors="replace").strip()
            
        except FileNotFoundError:
            raise FileNotFoundError("git executable not found. Please ensure git is installed.")
        except asyncio.TimeoutError:
            raise TimeoutError(f"git {' '.join(args)} timed out after {timeout}s")
        finally:
            if proc and proc.returncode is None:
                async def _cleanup():
                    try:
                        proc.terminate()
                        await asyncio.wait_for(proc.wait(), timeout=1.0)
                    except (asyncio.TimeoutError, ProcessLookupError):
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                await asyncio.shield(_cleanup())

    async def _get_base_commit(self) -> str:
        """Determines the base commit to compare against."""
        # Try to find common upstream candidates
        candidates = ["@{u}", "origin/main", "origin/master", "origin/HEAD"]
        for candidate in candidates:
            try:
                commit = await self._run_git_command(
                    "merge-base", "HEAD", candidate, timeout=5.0
                )
                if commit:
                    return commit
            except (subprocess.CalledProcessError, TimeoutError):
                continue

        # Fallback to the initial commit
        try:
            roots_out = await self._run_git_command(
                "rev-list", "--max-parents=0", "HEAD", timeout=5.0
            )
            root_commit = roots_out.splitlines()[0] if roots_out else ""
            if root_commit:
                return root_commit
        except (subprocess.CalledProcessError, TimeoutError, IndexError):
            pass

        raise RuntimeError(
            "Failed to determine a base commit for local changes. "
            "Make sure you are in a valid git repository with at least one commit."
        )

    async def fetch_change(
        self, target: str, output_dir: Path, vync_app: Vync
    ) -> ChangeInfo:
        output_dir.mkdir(parents=True, exist_ok=True)

        is_specific_commit = target.lower().startswith("local:")
        target_sha = target.split(":", 1)[1] if is_specific_commit else None

        change_info = ChangeInfo(
            cl_id=target_sha or "local",
            host="localhost",
            subject=f"Local Change {target_sha}" if target_sha else "Local Change",
            message="Diff from local repository",
            author_name="Local User",
        )

        try:
            if target_sha:
                base_commit = f"{target_sha}^"
                head_commit = target_sha
            else:
                base_commit = await self._get_base_commit()
                head_commit = None

            repo_root_str = await self._run_git_command(
                "rev-parse", "--show-toplevel", timeout=5.0
            )
            repo_root = Path(repo_root_str) # Already absolute from git rev-parse
        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

        async def _fetch_diff() -> None:
            """Generates the patch file."""
            diff_file = output_dir / "diff.patch"
            args = ["diff", base_commit]
            if head_commit:
                args.append(head_commit)
            
            with open(diff_file, "wb") as f:
                await self._run_git_command(*args, cwd=repo_root, stdout=f)

        async def _fetch_files() -> None:
            """Copies changed files to the output directory."""
            diff_args = ["diff", "--name-only", "-z", "--diff-filter=d", base_commit]
            if head_commit:
                diff_args.append(head_commit)
            
            files_out = await self._run_git_command(
                *diff_args, cwd=repo_root, return_bytes=True
            )
            if not files_out:
                return

            files = [f.decode("utf-8", errors="replace") for f in files_out.split(b"\0") if f]

            if not is_specific_commit:
                # For uncommitted changes, copy files directly from working tree.
                # Parallelize copying for performance.
                async def _copy_one(f_path):
                    src = repo_root / f_path
                    dst = output_dir / f_path
                    if await asyncio.to_thread(src.is_file):
                        await asyncio.to_thread(dst.parent.mkdir, parents=True, exist_ok=True)
                        await asyncio.to_thread(shutil.copy2, src, dst)

                await asyncio.gather(*[_copy_one(f) for f in files])
            else:
                # For a specific commit, use git archive to get files as they were in that commit.
                chunk_size = 50 # Reduced chunk size to avoid potential issues
                for i in range(0, len(files), chunk_size):
                    chunk = files[i : i + chunk_size]
                    chunk_quoted = [shlex.quote(f) for f in chunk]
                    
                    # Using exec instead of shell for better safety and overhead
                    # But git archive | tar needs a shell or manual pipe management.
                    # We'll use shell but ensure we wait and check return code.
                    cmd = f"git archive --format=tar {shlex.quote(head_commit)} {' '.join(chunk_quoted)} | tar -xf - -C {shlex.quote(str(output_dir))}"
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        cwd=repo_root,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE
                    )
                    try:
                        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
                        if proc.returncode != 0:
                            raise RuntimeError(f"git archive failed: {stderr.decode(errors='replace')}")
                    finally:
                        if proc.returncode is None:
                            proc.terminate()

        # Track tasks via Vync and wait for them to complete.
        exceptions: List[Exception] = []
        async def _wrapped_job(coro, job_name):
            try:
                await coro
            except Exception as e:
                exceptions.append(e)
                print(f"Job '{job_name}' failed: {e}")
                raise

        vync_app.TrackJob("Fetch Local Diff", _wrapped_job(_fetch_diff(), "Fetch Local Diff"))
        vync_app.TrackJob("Fetch Local Files", _wrapped_job(_fetch_files(), "Fetch Local Files"))
        
        await vync_app.await_all()
        
        if exceptions:
            shutil.rmtree(output_dir, ignore_errors=True)
            # Combine multiple errors if they occurred
            if len(exceptions) > 1:
                raise RuntimeError(f"Multiple failures during fetch: {exceptions}")
            raise exceptions[0]

        save_file(output_dir / "commit_info", "Local Changes Review\n")
        return change_info

    def get_reviewer_agents_dir(self) -> Path:
        base_dir = Path(__file__).parent.parent
        if self.mock:
            return base_dir / "mock_agents"
        return base_dir / "agents"
