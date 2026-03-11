"""
Fetches extra context files from Gerrit.
"""

from pathlib import Path

from core.gerrit_client import GerritClient
from core.models import AnalysisResult, ChangeInfo
from core.utils import save_file
from core.exceptions import GerritAPIError

def fetch_extra_context(cl_dir: Path, change_info: ChangeInfo, analysis: AnalysisResult) -> None:
    """
    Downloads the extra files identified by the analysis module using the Gerrit API.
    """
    if not analysis.extra_context_files:
        print("No extra context files to download.")
        return

    client = GerritClient(change_info.host)
    
    print(f"Fetching {len(analysis.extra_context_files)} extra context files...")
    
    for file_path in analysis.extra_context_files:
        try:
            original_bytes = client.fetch_original_file(change_info.cl_id, file_path)
            local_file_path = cl_dir / file_path
            save_file(local_file_path, original_bytes)
            print(f"- Saved: {local_file_path}")
        except GerritAPIError as e:
            print(f"- Failed to fetch '{file_path}': {e.status_code} {e.details}")
        except Exception as e:
            print(f"- Failed to fetch '{file_path}': {e}")
