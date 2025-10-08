import json
from datetime import datetime

# Load the conversations.json file
with open("conversations.json", "r", encoding="utf-8") as f:
    data = json.load(f)

def ts_to_str(ts):
    """Convert a float timestamp (epoch) to human-readable string."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")

# Go through each conversation block
for convo in data:
    title = convo.get("title", "Untitled")
    create_time = ts_to_str(convo.get("create_time"))
    update_time = ts_to_str(convo.get("update_time"))

    # Count messages inside mapping
    mapping = convo.get("mapping", {})
    message_count = sum(1 for m in mapping.values() if m.get("message"))

    print(f"Title: {title}")
    print(f"  Start: {create_time}")
    print(f"  End:   {update_time}")
    print(f"  Messages: {message_count}")
    print("-" * 60)

