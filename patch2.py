import re

with open("main.py", "r") as f:
    text = f.read()

old_run_review = """        run_review(
            cl_dir=output_dir,
            gemini_client=gemini_client,
            model_name=model_name,
            agents_dir=agents_dir,
            vync_app=vync_app
        )"""

new_run_review = """        async def _run_review():
            await run_review(
                cl_dir=output_dir,
                gemini_client=gemini_client,
                model_name=model_name,
                agents_dir=agents_dir,
                vync_app=vync_app
            )
        vync_app.TrackJob("Review Orchestrator", _run_review())
        vync_app.WaitAll()"""

text = text.replace(old_run_review, new_run_review)

old_summarize = """        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")
        async def _run_summary():
            return await asyncio.to_thread(summarize_reviews, cl_dir=output_dir, gemini_client=gemini_client, model_name=model_name)

        # We can just run it synchronously since nothing else is running, but let's track it in Vync
        summary_ref = [None]
        async def _track_summary():
            summary_ref[0] = await _run_summary()
        vync_app.TrackJob("Summarize Reviews", _track_summary())
        vync_app.WaitAll()"""

new_summarize = """        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")

        summary_ref = [None]
        async def _track_summary():
            summary_ref[0] = await summarize_reviews(cl_dir=output_dir, gemini_client=gemini_client, model_name=model_name)
        vync_app.TrackJob("Summarize Reviews", _track_summary())
        vync_app.WaitAll()"""

text = text.replace(old_summarize, new_summarize)

with open("main.py", "w") as f:
    f.write(text)
print("done")
