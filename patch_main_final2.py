import re

with open("main.py", "r") as f:
    text = f.read()

# Replace step 5
regex = re.compile(
    r"        # Step 5: Summarize Reviews.*?(?=        final_summary)", re.DOTALL
)
new_step_5 = """        # Step 5: Summarize Reviews
        print_header(f"Consolidating Final Review ({model_name})")
        
        summary_ref = [None]
        async def _track_summary():
            summary_ref[0] = await summarize_reviews(cl_dir=output_dir, gemini_client=gemini_client, model_name=model_name)
        vync_app.TrackJob("Summarize Reviews", _track_summary())
        vync_app.WaitAll()

"""
text = regex.sub(new_step_5, text)

with open("main.py", "w") as f:
    f.write(text)
