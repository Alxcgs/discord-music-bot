import json
import re

log_path = "/Users/alxcgs/.gemini/antigravity-ide/brain/47997560-e6a3-4269-9fa5-51d4282a75a8/.system_generated/logs/transcript.jsonl"

def extract_lines(content):
    line_pat = re.compile(r"^(\d+): (.*)$")
    extracted = {}
    for l in content.splitlines():
        m = line_pat.match(l.strip())
        if m:
            num = int(m.group(1))
            val = m.group(2)
            extracted[num] = val
    return extracted

with open(log_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines in log: {len(lines)}")

# Extract content from Log Line 1175
data_1175 = json.loads(lines[1175])
content_1175 = data_1175.get("content", "")
lines_1175 = extract_lines(content_1175)
print(f"Log Line 1175: extracted {len(lines_1175)} lines.")

# Extract content from Log Line 1179
data_1179 = json.loads(lines[1179])
content_1179 = data_1179.get("content", "")
lines_1179 = extract_lines(content_1179)
print(f"Log Line 1179: extracted {len(lines_1179)} lines.")

# Merge lines
merged_lines = {}
merged_lines.update(lines_1175)
merged_lines.update(lines_1179)

if not merged_lines:
    print("Error: No lines extracted!")
    exit(1)

max_line = max(merged_lines.keys())
print(f"Total merged lines: {len(merged_lines)}, max line index: {max_line}")

output_path = "/Users/alxcgs/Para/git-ds/discord-music-bot/Diploma/Кваліфікаційна робота Герасимчук.md"
with open(output_path, "w", encoding="utf-8") as out:
    for i in range(1, max_line + 1):
        out.write(merged_lines.get(i, "") + "\n")

print(f"Wrote recovered file to {output_path}")
