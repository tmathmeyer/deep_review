import sys
import re

with open("main.py", "r") as f:
    text = f.read()

old_block = """        # Step 2: Analyze Context
        print_header(f"Analyzing Context ({model_name})")
        analysis_ref = [None]
        async def _run_analysis():
            analysis_ref[0] = await asyncio.to_thread(analyze_context, output_dir, gemini_client, model_name, agents_dir)
        vync_app.TrackJob("Analyze Context", _run_analysis())
        vync_app.WaitAll()
        analysis = analysis_ref[0]

        if not analysis:
            print("Failed to analyze context. Aborting.")
            sys.exit(1)

        # Clean up project_tree so it doesn't pollute the review context
        project_tree_path = output_dir / "project_tree"
        if project_tree_path.exists():
            project_tree_path.unlink()

        # Step 3: Fetch Extra Context
        print_header("Loading Extra Context")
        fetch_extra_context(output_dir, change_info, analysis, vync_app)

        # Step 4: Perform Review
        print_header(f"Performing Multi-Agent Code Review ({model_name})")

        # Count agents to allocate dashboard space
        num_agents = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0

        if num_agents == 0:
            print(f"No agents found in {agents_dir.name}. Skipping review.")
            sys.exit(0)

        run_review(
            cl_dir=output_dir,
            gemini_client=gemini_client,
            model_name=model_name,
            agents_dir=agents_dir,
            vync_app=vync_app
        )

        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")
        async def _run_summary():
            return await asyncio.to_thread(summarize_reviews, cl_dir=output_dir, gemini_client=gemini_client, model_name=model_name)

        # We can just run it synchronously since nothing else is running, but let's track it in Vync
        summary_ref = [None]
        async def _track_summary():
            summary_ref[0] = await _run_summary()
        vync_app.TrackJob("Summarize Reviews", _track_summary())
        vync_app.WaitAll()

        final_summary = summary_ref[0]"""

new_block = """        # Step 2: Analyze Context
        print_header(f"Analyzing Context ({model_name})")
        analysis_ref = [None]
        async def _run_analysis():
            analysis_ref[0] = await analyze_context(output_dir, gemini_client, model_name, agents_dir)
        vync_app.TrackJob("Analyze Context", _run_analysis())
        vync_app.WaitAll()
        analysis = analysis_ref[0]

        if not analysis:
            print("Failed to analyze context. Aborting.")
            sys.exit(1)

        # Clean up project_tree so it doesn't pollute the review context
        project_tree_path = output_dir / "project_tree"
        if project_tree_path.exists():
            project_tree_path.unlink()

        # Step 3: Fetch Extra Context
        print_header("Loading Extra Context")
        fetch_extra_context(output_dir, change_info, analysis, vync_app)

        # Step 4: Perform Review
        print_header(f"Performing Multi-Agent Code Review ({model_name})")

        # Count agents to allocate dashboard space
        num_agents = len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0

        if num_agents == 0:
            print(f"No agents found in {agents_dir.name}. Skipping review.")
            sys.exit(0)

        async def _run_review():
            await run_review(
                cl_dir=output_dir,
                gemini_client=gemini_client,
                model_name=model_name,
                agents_dir=agents_dir,
                vync_app=vync_app
            )
        vync_app.TrackJob("Review Orchestrator", _run_review())
        vync_app.WaitAll()

        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")
        
        summary_ref = [None]
        async def _track_summary():
            summary_ref[0] = await summarize_reviews(cl_dir=output_dir, gemini_client=gemini_client, model_name=model_name)
        vync_app.TrackJob("Summarize Reviews", _track_summary())
        vync_app.WaitAll()

        final_summary = summary_ref[0]"""

if old_block in text:
    text = text.replace(old_block, new_block)
    with open("main.py", "w") as f:
        f.write(text)
    print("Success")
else:
    print("Could not find block")
