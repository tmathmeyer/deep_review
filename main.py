"""
main.py

Orchestrates the entire code review pipeline by calling the necessary scripts
in sequence:
1. load_change.py: Downloads the diff and original files.
2. analyze_change.py: Generates a summary and identifies extra context files.
3. load_extra_context.py: Downloads the identified extra context files.
4. review.py: Runs multi-agent parallel code review.

Usage: python3 main.py <gerrit-cl-url>
"""

import sys
import subprocess
import re

def run_step(command, step_name):
    print(f"\n{'='*50}")
    print(f"--- STEP: {step_name} ---")
    print(f"Running: {' '.join(command)}")
    print(f"{'='*50}")

    try:
        # Use check_call to raise an exception if the command fails
        subprocess.check_call(command)
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Error: Step '{step_name}' failed with exit code {e.returncode}.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[!] Process interrupted by user.")
        sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 main.py <gerrit-cl-url>")
        sys.exit(1)

    url = sys.argv[1]

    # Extract the CL ID from the URL to pass to the subsequent scripts
    # Example: https://chromium-review.googlesource.com/c/chromium/src/+/7652046
    match = re.search(r'\+/(\d+)', url)
    if match:
        cl_id = match.group(1)
    elif url.isdigit():
        cl_id = url
    else:
        print("Error: Could not extract numeric CL ID from the provided URL.")
        sys.exit(1)

    print(f"Starting review pipeline for CL: {cl_id}")

    # 1. Load the change
    run_step([sys.executable, "load_change.py", url], "Load Change")

    # 2. Analyze the change to generate summary and context file list
    run_step([sys.executable, "analyze_change.py", cl_id], "Analyze Change")

    # 3. Load the extra context files
    run_step([sys.executable, "load_extra_context.py", cl_id], "Load Extra Context")

    # 4. Perform the final multi-agent code review
    run_step([sys.executable, "review.py", cl_id], "Perform Code Review")

    print(f"\n{'+'*50}")
    print(f"SUCCESS: Pipeline complete!")
    print(f"Check the '{cl_id}/code_review.md' file for the final results.")
    print(f"{'+'*50}")

if __name__ == "__main__":
    main()
