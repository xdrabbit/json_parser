import json
from datetime import datetime

INPUT_FILE = "conversations.json"
OUTPUT_FILE = "Sensory_Sounds_of_Eating.txt"
TARGET_TITLE = "Sensory Sounds of Eating"

def ts_to_str(ts):
    """Convert epoch float to human-readable timestamp."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")

def normalize_parts(parts):
    """Make sure all parts become strings, extracting 'text' where possible."""
    normalized = []
    for p in parts:
        if isinstance(p, str):
            normalized.append(p)
        elif isinstance(p, dict) and "text" in p:
            normalized.append(p["text"])
        else:
            normalized.append(str(p))
    return " ".join(normalized).strip()

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

found = False
for convo in data:
    if convo.get("title") == TARGET_TITLE:
        found = True
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            out.write(f"=== Conversation: {convo['title']} ===\n")
            out.write(f"Start: {ts_to_str(convo.get('create_time'))}\n")
            out.write(f"End:   {ts_to_str(convo.get('update_time'))}\n\n")

            mapping = convo.get("mapping", {})
            messages = []
            for m in mapping.values():
                msg = m.get("message")
                if msg and msg.get("content"):
                    ts = msg.get("create_time")
                    role = msg["author"]["role"].upper()
                    parts = msg["content"].get("parts", [])
                    text = normalize_parts(parts)
                    if text:  # only write non-empty lines
                        messages.append((ts, role, text))

            # Sort by timestamp
            messages.sort(key=lambda x: x[0] if x[0] else 0)

            # Write all messages
            for i, (ts, role, text) in enumerate(messages, 1):
                out.write(f"[{i}] {ts_to_str(ts)} {role}: {text}\n\n")

        print(f"Transcript saved to {OUTPUT_FILE} with {len(messages)} messages.")
        break

if not found:
    print(f"Conversation '{TARGET_TITLE}' not found in {INPUT_FILE}")
