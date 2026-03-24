"""
Fetches the changelist from Gerrit and saves the initial files.
"""

import asyncio
import re
from vync import Vync
from pathlib import Path

from core.gerrit_client import GerritClient
from core.models import ChangeInfo
from core.utils import save_file


def parse_gerrit_url(url: str) -> tuple[str, str]:
    """Parses a Gerrit URL into (host, change_id)."""
    match = re.search(r"https://([^/]+)/.*/\+/(\d+)", url)
    if match:
        return match.group(1), match.group(2)
    elif url.isdigit():
        return "chromium-review.googlesource.com", url
    else:
        raise ValueError("Could not parse change ID from input.")


async def fetch_change(url: str, output_dir: Path, vync_app: Vync) -> ChangeInfo:
    """
    Fetches change metadata, the patch diff, and the original files
    for a given Gerrit URL, saving them to output_dir.
    """
    host, change_id = parse_gerrit_url(url)
    client = GerritClient(host)

    output_dir.mkdir(parents=True, exist_ok=True)

    print("Fetching change info...")
    # Use to_thread for the synchronous GerritClient calls
    info_json = await asyncio.to_thread(client.fetch_change_info, change_id)

    project = info_json.get("project", "")
    numeric_id = info_json.get("_number", change_id)
    current_rev = info_json.get("current_revision", "")
    commit_url = f"https://{host}/c/{project}/+/{numeric_id}"

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

    change_info = ChangeInfo(
        cl_id=str(numeric_id),
        host=host,
        project=project,
        branch=info_json.get("branch", "UNKNOWN"),
        status=info_json.get("status", "UNKNOWN"),
        patch_set=str(patch_set_num),
        author_name=author_name,
        author_email=author_email,
        created=info_json.get("created", "UNKNOWN"),
        updated=info_json.get("updated", "UNKNOWN"),
        subject=subject,
        message=message,
        commit_url=commit_url,
        gitiles_link=gitiles_link,
    )

    # Save commit_info
    commit_info_content = (
        f"Commit URL: {change_info.commit_url}\n"
        f"Gitiles Link: {change_info.gitiles_link if change_info.gitiles_link else 'Not available'}\n"
        f"Project: {change_info.project}\n"
        f"Branch: {change_info.branch}\n"
        f"Status: {change_info.status}\n"
        f"Patch Set: {change_info.patch_set}\n"
        f"Author: {change_info.author_name} <{change_info.author_email}>\n"
        f"Created: {change_info.created}\n"
        f"Updated: {change_info.updated}\n"
        f"\nSubject: {change_info.subject}\n"
        f"\nCommit Message:\n{change_info.message}\n"
    )
    save_file(output_dir / "commit_info", commit_info_content)
    print(f"Saved commit info to: {output_dir / 'commit_info'}")

    # Fetch and save diff
    async def _fetch_diff():
        patch_bytes = await asyncio.to_thread(client.fetch_patch_diff, change_id, 20)
        save_file(output_dir / "diff.patch", patch_bytes)

    vync_app.TrackJob("Fetch Diff", _fetch_diff())

    # Fetch changed files
    files_data = await asyncio.to_thread(client.fetch_changed_files, change_id)
    modified_files = []

    # Limit concurrency to avoid overwhelming the server
    semaphore = asyncio.Semaphore(10)

    async def _fetch_orig(fp):
        async with semaphore:
            try:
                original_bytes = await asyncio.to_thread(
                    client.fetch_original_file, change_id, fp
                )
                save_file(output_dir / fp, original_bytes)
            except Exception as e:
                print(f"Error fetching original file {fp}: {e}")
                # We don't raise here to allow other files to be fetched, 
                # but we've logged it.

    for file_path in files_data.keys():
        if file_path == "/COMMIT_MSG":
            continue
        modified_files.append(file_path)
        vync_app.TrackJob(f"Fetch {file_path}", _fetch_orig(file_path))

    await vync_app.await_all()

    # Discover and save project tree
    deep_dirs = set()
    for file_path in modified_files:
        parts = file_path.split("/")
        if len(parts) > 1:
            deep_dirs.add("/".join(parts[:-1]))

    shallow_dirs = set([""])  # Always include root

    for dir_path in deep_dirs:
        parts = dir_path.split("/")
        for i in range(1, len(parts)):
            shallow_dirs.add("/".join(parts[:i]))

    tree_files = set()
    commit_id = current_rev if current_rev else "HEAD"

    try:
        root_data = await asyncio.to_thread(
            client.fetch_gitiles_directory, 
            project, commit_id, "", gitiles_commit_url=change_info.gitiles_link
        )
        for entry in root_data.get("entries", []):
            if entry.get("type") == "tree":
                shallow_dirs.add(entry.get("name"))
    except Exception as e:
        print(f"Warning: Failed to fetch root directory tree: {e}")

    shallow_dirs = shallow_dirs - deep_dirs
    shallow_dirs.add("")

    async def _fetch_shallow(dp):
        async with semaphore:
            try:
                dir_data = await asyncio.to_thread(
                    client.fetch_gitiles_directory,
                    project,
                    commit_id,
                    dp,
                    change_info.gitiles_link,
                )
                entries = dir_data.get("entries", [])
                for entry in entries:
                    if entry.get("type") == "blob":
                        file_name = entry.get("name")
                        full_path = f"{dp}/{file_name}" if dp else file_name
                        tree_files.add(full_path)
            except Exception as e:
                print(f"Warning: Failed to list directory {dp}: {e}")

    for dir_path in sorted(list(shallow_dirs)):
        vync_app.TrackJob(f"List Dir {dir_path}", _fetch_shallow(dir_path))

    async def _fetch_deep(dp):
        async with semaphore:
            try:
                dir_data = await asyncio.to_thread(
                    client.fetch_gitiles_directory,
                    project,
                    commit_id,
                    dp,
                    change_info.gitiles_link,
                    True,
                )
                entries = dir_data.get("entries", [])
                for entry in entries:
                    if entry.get("type") == "blob":
                        file_name = entry.get("name")
                        full_path = f"{dp}/{file_name}" if dp else file_name
                        tree_files.add(full_path)
            except Exception as e:
                print(f"Warning: Failed to list deep directory {dp}: {e}")

    for dir_path in sorted(list(deep_dirs)):
        if not dir_path:
            continue
        vync_app.TrackJob(f"List Deep Dir {dir_path}", _fetch_deep(dir_path))

    await vync_app.await_all()

    if tree_files:
        tree_content = (
            "Project files near the changed files:\n\n"
            + "\n".join(sorted(list(tree_files)))
            + "\n"
        )
        save_file(output_dir / "project_tree", tree_content)

    return change_info
