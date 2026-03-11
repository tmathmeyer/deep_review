"""
review.py

This script takes a Changelist (CL) directory and reads all the files within it
(skipping files over 5000 lines). It uses the Gemini REST API to prepare a cached
context of the codebase, and then prompts the Gemini model to perform a thorough
code review.

The review focuses on logic, memory safety, buffer safety, and other implementation details,
outputting strictly negative feedback with file and line references.

The output is saved to a `code_review.md` file inside the CL directory.

Usage: python3 review.py <cl-dir-number>
"""

import os
import sys
import json
import urllib.request
import urllib.error
import concurrent.futures

def get_file_contents(cl_dir):
    contents = []
    delayed_files = []

    # Walk through the directory to find all downloaded files
    for root, dirs, files in os.walk(cl_dir):
        for file in files:
            file_path = os.path.join(root, file)

            # Skip output files to avoid recursive prompting
            if file in ("pre_review", "extra_context_files", "code_review.md"):
                continue

            # Save diff.patch and summary to process them last
            if file in ("diff.patch", "summary"):
                delayed_files.append(file_path)
                continue

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    if len(lines) > 5000:
                        print(f"Skipping {file_path} (more than 5000 lines)")
                        continue

                    file_content = "".join(lines)
                    contents.append(f"--- File: {file_path} ---\n{file_content}\n")
            except UnicodeDecodeError:
                print(f"Skipping {file_path} (binary or non-UTF-8 content)")
            except Exception as e:
                print(f"Skipping {file_path} due to error: {e}")

    # Process the delayed files (diff.patch and summary) last
    # Try to order them specifically if both exist (e.g., summary then diff.patch)
    delayed_files.sort(key=lambda x: 1 if "diff.patch" in x else 0)

    for file_path in delayed_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                if len(lines) > 5000:
                    print(f"Skipping {file_path} (more than 5000 lines)")
                    continue

                file_content = "".join(lines)
                contents.append(f"--- File: {file_path} ---\n{file_content}\n")
        except Exception as e:
            print(f"Skipping {file_path} due to error: {e}")

    return contents

def create_cached_content(api_key, model_name, document_text):
    # caching requires the model path like "models/gemini-1.5-pro-001"
    url = f"https://generativelanguage.googleapis.com/v1beta/cachedContents?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {
        "model": f"models/{model_name}",
        "contents": [{
            "parts": [{"text": document_text}],
            "role": "user"
        }],
        "ttl": "600s"
    }

    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('name')
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"Failed to create cache: HTTP {e.code}")
        print(f"Details: {error_body}")
        return None
    except Exception as e:
        print(f"Failed to create cache: {e}")
        return None

def delete_cached_content(api_key, cache_name):
    url = f"https://generativelanguage.googleapis.com/v1beta/{cache_name}?key={api_key}"
    req = urllib.request.Request(url, method='DELETE')
    try:
        urllib.request.urlopen(req)
        print("Cached content deleted.")
    except Exception as e:
        print(f"Failed to delete cache: {e}")

def call_gemini_api(api_key, model_name, prompt, document_text=None, cache_name=None):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    data = {
        "contents": [{
            "parts": [{"text": prompt}],
            "role": "user"
        }],
        "generationConfig": {
            "temperature": 0.2
        }
    }

    if cache_name:
        data["cachedContent"] = cache_name
    elif document_text:
        # Fallback to including the document directly
        data["contents"][0]["parts"].insert(0, {"text": document_text + "\n\n"})

    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            try:
                text = result['candidates'][0]['content']['parts'][0]['text']
                usage = result.get('usageMetadata', {})
                return text, usage
            except (KeyError, IndexError):
                print("Unexpected response structure from Gemini API:")
                print(json.dumps(result, indent=2))
                return None, None
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"HTTP Error {e.code}: {e.reason}")
        print(f"Details: {error_body}")
        return None, None
    except Exception as e:
        print(f"Failed to communicate with Gemini API: {e}")
        return None, None

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 review.py <cl-dir>")
        sys.exit(1)

    cl_dir = sys.argv[1]
    if not os.path.isdir(cl_dir):
        print(f"Error: Directory '{cl_dir}' does not exist.")
        sys.exit(1)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        sys.exit(1)

    # Read agent prompts from the 'agents' directory
    agents_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agents")
    if not os.path.isdir(agents_dir):
        print(f"Error: Agents directory '{agents_dir}' does not exist.")
        sys.exit(1)

    agents = []
    for filename in os.listdir(agents_dir):
        if filename.endswith(".md"):
            agent_name = filename[:-3]
            with open(os.path.join(agents_dir, filename), "r", encoding="utf-8") as f:
                agent_prompt = f.read()
            agents.append((agent_name, agent_prompt))

    if not agents:
        print(f"Error: No agent prompts (.md files) found in '{agents_dir}'.")
        sys.exit(1)

    print(f"Reading files in '{cl_dir}'...")
    file_contents = get_file_contents(cl_dir)
    if not file_contents:
        print("No valid files found to analyze.")
        sys.exit(1)

    document_text = "\n".join(file_contents)

    # The user specifically requested this model
    #model_name = 'gemini-3.1-pro-preview'
    model_name = 'gemini-3-flash-preview'

    print("Attempting to create cached context...")
    cache_name = create_cached_content(api_key, model_name, document_text)

    # Save the full context to a file for debugging/visibility
    full_context_file = os.path.join(cl_dir, "full_context")
    with open(full_context_file, "w", encoding="utf-8") as f:
        f.write(document_text)
    print(f"Saved complete context to {full_context_file}")

    if cache_name:
        print(f"Context cached successfully ({cache_name}).")
    else:
        print("Caching failed or is unsupported for this context size. Falling back to direct API requests...")
    import time
    import threading

    agent_states = {agent_name: {'status': 'Pending', 'start': 0, 'elapsed': 0} for agent_name, _ in agents}
    dashboard_active = True
    dashboard_lock = threading.Lock()

    def dashboard_thread_func():
        # Hide cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        while dashboard_active:
            with dashboard_lock:
                # Move cursor up to the top of the dashboard
                sys.stdout.write(f"\033[{len(agents) + 2}A")

                print("-" * 40 + "\033[K") # \033[K clears the rest of the line
                for name in sorted(agent_states.keys()):
                    state = agent_states[name]
                    if state['status'] == 'Running':
                        elapsed = time.time() - state['start']
                        print(f"[\033[93m~\033[0m] {name:<20} | Running ({elapsed:.1f}s)\033[K")
                    elif state['status'] == 'Done':
                        print(f"[\033[92m✓\033[0m] {name:<20} | Done ({state['elapsed']:.1f}s)\033[K")
                    elif state['status'] == 'Failed':
                        print(f"[\033[91mx\033[0m] {name:<20} | Failed\033[K")
                    else:
                        print(f"[ ] {name:<20} | Pending\033[K")
                print("-" * 40 + "\033[K")
            time.sleep(0.2)

        # Restore cursor
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    def run_agent(agent_data):
        agent_name, prompt = agent_data

        with dashboard_lock:
            agent_states[agent_name]['status'] = 'Running'
            agent_states[agent_name]['start'] = time.time()

        if cache_name:
            response_text, usage = call_gemini_api(api_key, model_name, prompt, cache_name=cache_name)
        else:
            response_text, usage = call_gemini_api(api_key, model_name, prompt, document_text=document_text)

        with dashboard_lock:
            agent_states[agent_name]['elapsed'] = time.time() - agent_states[agent_name]['start']
            if response_text:
                agent_states[agent_name]['status'] = 'Done'
                agent_states[agent_name]['usage'] = usage
            else:
                agent_states[agent_name]['status'] = 'Failed'

        if response_text:
            return f"## Review by {agent_name}\n\n{response_text}", usage
        else:
            return f"## Review by {agent_name}\n\n(Failed to get review from this agent)", None

    all_reviews = []
    total_usage = {'prompt': 0, 'candidates': 0, 'total': 0}

    # Run agents in parallel using a thread pool
    max_workers = min(10, len(agents))
    print(f"\nStarting {len(agents)} review agents in parallel...")

    # Allocate empty lines for the dashboard to overwrite
    print("\n" * (len(agents) + 2))

    dashboard_thread = threading.Thread(target=dashboard_thread_func)
    dashboard_thread.start()

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        future_to_agent = {executor.submit(run_agent, agent): agent for agent in agents}

        # Collect results as they complete
        for future in concurrent.futures.as_completed(future_to_agent):
            agent_data = future_to_agent[future]
            agent_name = agent_data[0]
            try:
                result_text, usage = future.result()
                all_reviews.append(result_text)
                if usage:
                    total_usage['prompt'] += usage.get('promptTokenCount', 0)
                    total_usage['candidates'] += usage.get('candidatesTokenCount', 0)
                    total_usage['total'] += usage.get('totalTokenCount', 0)
            except Exception as exc:
                with dashboard_lock:
                    agent_states[agent_name]['status'] = 'Failed'
                all_reviews.append(f"## Review by {agent_name}\n\n(Exception occurred: {exc})")

    # Stop the dashboard thread
    dashboard_active = False
    dashboard_thread.join()

    if cache_name:
        delete_cached_content(api_key, cache_name)

    stats_md = f"\n\n---\n\n## LLM Usage Stats\n"
    stats_md += f"- **Total Prompt Tokens:** {total_usage['prompt']}\n"
    stats_md += f"- **Total Candidate Tokens:** {total_usage['candidates']}\n"
    stats_md += f"- **Total Tokens:** {total_usage['total']}\n"

    # Save the output to the code_review.md file
    out_file = os.path.join(cl_dir, "code_review.md")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n\n---\n\n".join(all_reviews))
        f.write(stats_md)

    print(f"\nReview complete! Saved to {out_file}")
    print(f"\nLLM Stats: {total_usage['prompt']} Prompt | {total_usage['candidates']} Generated | {total_usage['total']} Total Tokens")
if __name__ == "__main__":
    main()
