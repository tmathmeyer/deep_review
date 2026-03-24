import asyncio
import subprocess
import shutil
import sys
import shlex
from pathlib import Path
from core.reviewer import Reviewer
from core.models import ChangeInfo
from vync import Vync
from core.utils import save_file


class LocalReviewer(Reviewer):
    @classmethod
    def handles_target(cls, target: str) -> bool:
        return target.lower() == "local" or target.lower().startswith("local:")

    async def _run_git_command(
        self, *args: str, timeout: float = 30.0, return_bytes: bool = False
    ):
        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode == 0:
                if return_bytes:
                    return stdout
                return stdout.decode(errors="replace").strip()
            else:
                stderr_str = stderr.decode(errors="replace")
                raise subprocess.CalledProcessError(
                    proc.returncode,
                    f"git {' '.join(args)}",
                    output=stdout,
                    stderr=stderr_str,
                )
        except asyncio.TimeoutError:
            raise TimeoutError(f"git {' '.join(args)} timed out after {timeout}s")
        finally:
            if proc and proc.returncode is None:
                # Protect cleanup from cancellation
                async def _cleanup():
                    try:
                        proc.terminate()
                    except ProcessLookupError:
                        pass
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=1.0)
                    except asyncio.TimeoutError:
                        try:
                            proc.kill()
                        except ProcessLookupError:
                            pass
                        await proc.wait()

                await asyncio.shield(_cleanup())

    async def _get_base_commit(self) -> str:
        candidates = ["@{u}", "origin/main", "origin/master", "origin/HEAD"]
        for candidate in candidates:
            try:
                commit = await self._run_git_command(
                    "merge-base", "HEAD", candidate, timeout=5.0
                )
                if commit:
                    return commit
            except FileNotFoundError:
                print(
                    "\n[Error] git executable not found. Please ensure git is installed.",
                    file=sys.stderr,
                )
                raise
            except (subprocess.CalledProcessError, TimeoutError):
                pass

        # Fallback to the root commit or empty tree if no upstream exists to get all unpushed
        try:
            roots_out = await self._run_git_command(
                "rev-list", "--max-parents=0", "HEAD", timeout=5.0
            )
            root_commit, _, _ = roots_out.partition("\n")
            if root_commit.strip():
                return root_commit.strip()
        except FileNotFoundError:
            raise
        except (subprocess.CalledProcessError, TimeoutError):
            pass

        raise RuntimeError(
            "Failed to determine a base commit for local changes. Make sure you are in a valid git repository with at least one commit."
        )

    async def fetch_change(
        self, target: str, output_dir: Path, vync_app: Vync
    ) -> ChangeInfo:
        output_dir.mkdir(parents=True, exist_ok=True)

        is_specific_commit = target.lower().startswith("local:")
        target_sha = target.split(":", 1)[1] if is_specific_commit else None

        # We will track jobs for diff and files using vync
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
            repo_root = Path(str(repo_root_str)).resolve()
        except BaseException:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

        async def _fetch_diff() -> None:
            proc = None
            try:
                # Use zero-copy redirection by passing a file descriptor
                with open(output_dir / "diff.patch", "wb") as f:
                    args = ["git", "diff", base_commit]
                    if head_commit:
                        args.append(head_commit)
                    proc = await asyncio.create_subprocess_exec(
                        *args, cwd=repo_root, stdout=f, stderr=asyncio.subprocess.PIPE
                    )
                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
                    if proc.returncode != 0:
                        raise subprocess.CalledProcessError(
                            proc.returncode,
                            f"git diff {base_commit}",
                            stderr=stderr.decode(errors="replace"),
                        )
            except asyncio.TimeoutError:
                print(f"\n[Error] git diff timed out", file=sys.stderr)
                raise
            except subprocess.CalledProcessError as e:
                print(f"\n[Error] git diff error: {e.stderr}", file=sys.stderr)
                raise
            finally:
                if proc and proc.returncode is None:

                    async def _cleanup():
                        try:
                            proc.terminate()
                        except ProcessLookupError:
                            pass
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=1.0)
                        except asyncio.TimeoutError:
                            try:
                                proc.kill()
                            except ProcessLookupError:
                                pass
                            await proc.wait()

                    await asyncio.shield(_cleanup())

        vync_app.TrackJob("Fetch Local Diff", _fetch_diff())

        # Also get modified files to copy them to output_dir
        async def _fetch_files() -> None:
            proc = None
            try:
                if not is_specific_commit:
                    proc = await asyncio.create_subprocess_shell(
                        f"git diff --name-only -z --diff-filter=d {base_commit} | tar -cf - --null -T - | tar -xf - -C {shlex.quote(str(output_dir))}",
                        cwd=repo_root,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.PIPE,
                    )

                    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)

                    if proc.returncode != 0:
                        raise RuntimeError(
                            f"pipeline failed: {stderr.decode(errors='replace')}"
                        )
                else:
                    files_out = await self._run_git_command(
                        "diff",
                        "--name-only",
                        "-z",
                        "--diff-filter=d",
                        base_commit,
                        head_commit,
                        return_bytes=True,
                    )
                    if not files_out:
                        return

                    files = [
                        f.decode("utf-8", errors="replace")
                        for f in files_out.split(b"\0")
                        if f
                    ]

                    # chunk files to avoid ARG_MAX
                    chunk_size = 100
                    for i in range(0, len(files), chunk_size):
                        chunk = files[i : i + chunk_size]
                        # git archive --format=tar {head_commit} {chunk} | tar -xf - -C {output_dir}
                        chunk_quoted = " ".join(shlex.quote(f) for f in chunk)
                        proc = await asyncio.create_subprocess_shell(
                            f"git archive --format=tar {shlex.quote(head_commit)} {chunk_quoted} | tar -xf - -C {shlex.quote(str(output_dir))}",
                            cwd=repo_root,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        _, stderr = await asyncio.wait_for(
                            proc.communicate(), timeout=60.0
                        )
                        if proc.returncode != 0:
                            raise RuntimeError(
                                f"git archive pipeline failed: {stderr.decode(errors='replace')}"
                            )
            except asyncio.TimeoutError:
                print(f"\n[Error] Pipeline timed out", file=sys.stderr)
                raise
            except Exception as e:
                print(f"\n[Error] Pipeline error: {e}", file=sys.stderr)
                raise
            finally:
                if proc and proc.returncode is None:

                    async def _cleanup_proc(proc_to_clean):
                        try:
                            proc_to_clean.terminate()
                        except ProcessLookupError:
                            pass
                        try:
                            await asyncio.wait_for(proc_to_clean.wait(), timeout=1.0)
                        except asyncio.TimeoutError:
                            try:
                                proc_to_clean.kill()
                            except ProcessLookupError:
                                pass
                            await proc_to_clean.wait()

                    await asyncio.shield(_cleanup_proc(proc))

        vync_app.TrackJob("Fetch Local Files", _fetch_files())

        try:
            # We use an asyncio.TaskGroup (if 3.11+) or gather with return_exceptions to ensure cancellation works.
            # If one task fails, gather cancels the others if we catch and handle it correctly.
            diff_task = asyncio.create_task(_fetch_diff())
            files_task = asyncio.create_task(_fetch_files())

            done, pending = await asyncio.wait(
                [diff_task, files_task], return_when=asyncio.FIRST_EXCEPTION
            )

            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            # Check for exceptions in done tasks
            for task in done:
                exc = task.exception()
                if exc:
                    raise exc

        except Exception:
            shutil.rmtree(output_dir, ignore_errors=True)
            raise

        # Save a fake commit info
        save_file(output_dir / "commit_info", "Local Changes Review\n")

        return change_info

    def get_reviewer_agents_dir(self) -> Path:
        base_dir = Path(__file__).parent.parent
        if self.mock:
            return base_dir / "mock_agents"
        return base_dir / "agents"
