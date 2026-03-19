import textwrap

with open("main.py", "r") as f:
    text = f.read()

# Let's fix lines 114 to 135
lines = text.split('\n')
start_idx = 0
for i, line in enumerate(lines):
    if "# Step 5: Summarize Reviews" in line:
        start_idx = i
        break

if start_idx > 0:
    for i in range(start_idx, start_idx + 8):
        lines[i] = "        " + lines[i].lstrip()

with open("main.py", "w") as f:
    f.write('\n'.join(lines))
