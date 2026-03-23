import streamlit as st
import json
import requests
import re
from datetime import datetime

stop_words = set("the and is in to a an for with on at by from as or but not this that it be have do will can".split())
MARKDOWN_IMAGE_RE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)')
FILE_ID_RE = re.compile(r'(file_[A-Za-z0-9]+)')

def syllable_count(word):
    word = word.lower()
    count = 0
    vowels = "aeiouy"
    if word[0] in vowels:
        count += 1
    for i in range(1, len(word)):
        if word[i] in vowels and word[i-1] not in vowels:
            count += 1
    if word.endswith("e"):
        count -= 1
    if count == 0:
        count += 1
    return count

def to_dotcode(text):
    words = re.findall(r'\b\w+\b', text.lower())
    filtered = [w for w in words if w not in stop_words]
    encoded = []
    for word in filtered:
        if len(word) > 1:
            consonants = ''.join(c for c in word if c not in 'aeiou')
            if not consonants:
                consonants = word[0]
            else:
                consonants = word[0] + consonants[1:3]  # first + next 2 cons
        else:
            consonants = word
        syl = syllable_count(word)
        dots = '.' * min(syl, 3)
        encoded.append(consonants + dots)
    return ' '.join(encoded)

def ts_to_str(ts):
    """Convert epoch float to human-readable timestamp."""
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")

def summarize_text(text, limit=220):
    """Collapse whitespace and clip long strings for manifests and previews."""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."

def extract_asset_id(value):
    """Extract a ChatGPT export file id from a URL or asset pointer."""
    if not value:
        return None
    match = FILE_ID_RE.search(str(value))
    return match.group(1) if match else None

def unique_preserve_order(values):
    """Deduplicate simple values while preserving order."""
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result

def unique_records(records):
    """Deduplicate dictionaries while preserving order."""
    result = []
    seen = set()
    for record in records:
        key = json.dumps(record, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            seen.add(key)
            result.append(record)
    return result

def extract_text_evidence(text):
    """Replace markdown image refs with readable markers and capture evidence metadata."""
    references = []

    def replace_match(match):
        alt_text = (match.group("alt") or "").strip() or "Uploaded image"
        url = match.group("url").strip()
        asset_id = extract_asset_id(url)
        marker = f"[Referenced image: {alt_text}]"
        references.append({
            "kind": "image_link",
            "label": alt_text,
            "marker": marker,
            "url": url,
            "asset_id": asset_id,
            "filename": None,
            "asset_pointer": None,
        })
        return marker

    cleaned_text = MARKDOWN_IMAGE_RE.sub(replace_match, text)
    return cleaned_text, references

def describe_attachment(part):
    """Summarize non-text payloads without dumping internal JSON blobs."""
    if not isinstance(part, dict):
        return None, None

    content_type = str(part.get("content_type") or part.get("type") or "").lower()
    filename = part.get("filename") or part.get("name") or part.get("title")
    asset_pointer = part.get("asset_pointer")
    asset_id = extract_asset_id(asset_pointer)
    url = part.get("url") or part.get("download_url") or part.get("href")

    if "image" in content_type:
        label = "image"
        kind = "image"
    elif "audio" in content_type:
        label = "audio"
        kind = "audio"
    elif "video" in content_type:
        label = "video"
        kind = "video"
    elif "file" in content_type:
        label = "file"
        kind = "file"
    elif asset_pointer:
        label = "attachment"
        kind = "attachment"
    else:
        return None, None

    if filename:
        marker = f"[Attachment: {label} - {filename}]"
    else:
        marker = f"[Attachment: {label}]"

    reference = {
        "kind": kind,
        "label": filename or label.title(),
        "marker": marker,
        "url": url,
        "asset_id": asset_id or extract_asset_id(url),
        "filename": filename,
        "asset_pointer": asset_pointer,
    }
    return marker, reference

def extract_content_text(content):
    """Return cleaned text, attachment markers, and evidence refs for a message."""
    if not isinstance(content, dict):
        return "", [], []

    text_segments = []
    attachments = []
    evidence_refs = []
    parts = content.get("parts", [])

    for part in parts:
        if isinstance(part, str):
            stripped = part.strip()
            if stripped:
                cleaned_text, extracted_refs = extract_text_evidence(stripped)
                text_segments.append(cleaned_text)
                attachments.extend([record["marker"] for record in extracted_refs])
                evidence_refs.extend(extracted_refs)
            continue

        if isinstance(part, dict):
            text_value = part.get("text")
            if isinstance(text_value, str) and text_value.strip():
                cleaned_text, extracted_refs = extract_text_evidence(text_value.strip())
                text_segments.append(cleaned_text)
                attachments.extend([record["marker"] for record in extracted_refs])
                evidence_refs.extend(extracted_refs)
                continue

            nested_parts = part.get("parts")
            if isinstance(nested_parts, list):
                nested_text, nested_attachments, nested_refs = extract_content_text({"parts": nested_parts})
                if nested_text:
                    text_segments.append(nested_text)
                attachments.extend(nested_attachments)
                evidence_refs.extend(nested_refs)
                continue

            attachment_marker, attachment_ref = describe_attachment(part)
            if attachment_marker:
                attachments.append(attachment_marker)
            if attachment_ref:
                evidence_refs.append(attachment_ref)

    if not parts:
        attachment_marker, attachment_ref = describe_attachment(content)
        if attachment_marker:
            attachments.append(attachment_marker)
        if attachment_ref:
            evidence_refs.append(attachment_ref)

    cleaned_text = "\n\n".join(segment for segment in text_segments if segment).strip()
    unique_attachments = unique_preserve_order(attachments)
    unique_evidence_refs = unique_records(evidence_refs)

    if unique_attachments:
        attachment_block = "\n".join(unique_attachments)
        if cleaned_text:
            cleaned_text = f"{cleaned_text}\n\n{attachment_block}"
        else:
            cleaned_text = attachment_block

    return cleaned_text.strip(), unique_attachments, unique_evidence_refs

def sanitize_filename(value):
    """Convert a conversation title into a safe filename stem."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return cleaned.strip("._") or "conversation"

def build_thread_export(convo, messages):
    """Create a flattened thread export for downstream tools and memory seeding."""
    return {
        "title": convo.get("title", "Untitled"),
        "create_time": convo.get("create_time"),
        "update_time": convo.get("update_time"),
        "participants": sorted({message["role"].lower() for message in messages}),
        "message_count": len(messages),
        "messages": [
            {
                "index": index,
                "timestamp": message["timestamp"],
                "role": message["role"].lower(),
                "content": message["content"],
                "attachments": message["attachments"],
                "evidence_refs": message["evidence_refs"],
            }
            for index, message in enumerate(messages, 1)
        ],
    }

def build_evidence_manifest(convo, messages):
    """Create a manifest of evidence references found in the thread."""
    exhibits = []
    exhibit_number = 1

    for index, message in enumerate(messages, 1):
        for reference in message["evidence_refs"]:
            exhibits.append({
                "exhibit_id": f"EXH-{exhibit_number:03d}",
                "conversation_title": convo.get("title", "Untitled"),
                "message_index": index,
                "timestamp": message["timestamp"],
                "role": message["role"].lower(),
                "kind": reference.get("kind", "attachment"),
                "label": reference.get("label") or reference.get("marker") or "Attachment",
                "marker": reference.get("marker"),
                "filename": reference.get("filename"),
                "asset_id": reference.get("asset_id"),
                "asset_pointer": reference.get("asset_pointer"),
                "source_url": reference.get("url"),
                "message_excerpt": summarize_text(message["content"]),
                "retrieval_note": "Use the asset id, source URL, or original export package to retrieve the full exhibit when needed.",
            })
            exhibit_number += 1

    return {
        "conversation_title": convo.get("title", "Untitled"),
        "create_time": convo.get("create_time"),
        "update_time": convo.get("update_time"),
        "evidence_count": len(exhibits),
        "exhibits": exhibits,
    }

def build_timeline_anchors(messages, limit=12):
    """Build concise anchors for chronology-heavy threads."""
    anchors = []
    for index, message in enumerate(messages[:limit], 1):
        anchors.append(f"- {ts_to_str(message['timestamp'])} [{index}] {message['role']}: {summarize_text(message['content'], 140)}")
    return anchors

def build_markdown_transcript(convo, messages):
    """Create a readable transcript for project sources."""
    lines = [
        f"# Conversation Transcript: {convo.get('title', 'Untitled')}",
        "",
        "## Metadata",
        f"- Title: {convo.get('title', 'Untitled')}",
        f"- Start: {ts_to_str(convo.get('create_time'))}",
        f"- End: {ts_to_str(convo.get('update_time'))}",
        f"- Message count: {len(messages)}",
        f"- Participants: {', '.join(sorted({message['role'].title() for message in messages})) or 'Unknown'}",
        "",
        "## Transcript",
        "",
    ]

    for index, message in enumerate(messages, 1):
        lines.extend([
            f"### [{index}] {message['role']} - {ts_to_str(message['timestamp'])}",
            "",
            message["content"],
            "",
        ])

    return "\n".join(lines).strip() + "\n"

def build_project_memory_markdown(convo, messages, evidence_manifest):
    """Create a layered, legal-oriented source document for seeding a ChatGPT Project."""
    transcript = build_markdown_transcript(convo, messages)
    participants = ", ".join(sorted({message["role"].title() for message in messages})) or "Unknown"
    exhibits = evidence_manifest["exhibits"]
    evidence_lines = [
        f"- {exhibit['exhibit_id']}: {exhibit['kind']} | {exhibit['label']} | message [{exhibit['message_index']}] | asset_id={exhibit['asset_id'] or 'n/a'}"
        for exhibit in exhibits[:15]
    ]
    if not evidence_lines:
        evidence_lines = ["- No explicit exhibits were extracted from this thread."]

    timeline_lines = build_timeline_anchors(messages)
    if not timeline_lines:
        timeline_lines = ["- No timeline anchors available."]

    lines = [
        f"# Project Memory Seed: {convo.get('title', 'Untitled')}",
        "",
        "## Source Metadata",
        f"- Source type: ChatGPT export conversation",
        f"- Title: {convo.get('title', 'Untitled')}",
        f"- Start: {ts_to_str(convo.get('create_time'))}",
        f"- End: {ts_to_str(convo.get('update_time'))}",
        f"- Participants: {participants}",
        f"- Message count: {len(messages)}",
        f"- Evidence references: {evidence_manifest['evidence_count']}",
        "",
        "## Layered Retrieval Strategy",
        "- Layer 1: Use this project memory for durable facts, issues, and next actions.",
        "- Layer 2: Use the clean transcript for detailed conversational context.",
        "- Layer 3: Use the evidence manifest to retrieve specific exhibits only when needed.",
        "- Layer 4: Use the original export package for the underlying files and raw JSON.",
        "",
        "## Legal Working Memory Seed",
        f"- Topic: {convo.get('title', 'Untitled')}",
        "- Matter summary: Populate after quick review of the transcript.",
        "- Durable facts:",
        "- Claims or positions:",
        "- Decisions already made:",
        "- Constraints or deadlines:",
        "- Open questions:",
        "- Next actions:",
        "",
        "## Timeline Anchors",
        *timeline_lines,
        "",
        "## Evidence Layer",
        *evidence_lines,
        "",
        "## Notes",
        "- This transcript was cleaned to remove raw internal asset-pointer payloads.",
        "- Attachment placeholders are preserved only as short markers when relevant.",
        "- Images and files should stay in lower layers unless they are central to the immediate question.",
        "",
        "## Clean Transcript",
        "",
        transcript,
    ]
    return "\n".join(lines).strip() + "\n"

def build_full_text(messages, input_mode):
    """Construct prompt input from cleaned messages."""
    if input_mode == "Full Conversation":
        selected_messages = messages
        return "\n".join([f"{message['role']}: {message['content']}" for message in selected_messages])
    if input_mode == "Last 20 Messages":
        selected_messages = messages[-20:]
        return "\n".join([f"{message['role']}: {message['content']}" for message in selected_messages])
    if input_mode == "Smart Summary (first 3 + last 10)":
        selected_messages = messages[:3] + messages[-10:]
        return "\n".join([f"{message['role']}: {message['content']}" for message in selected_messages])
    if input_mode == "JSON Structure":
        json_data = {
            "messages": [
                {
                    "timestamp": message["timestamp"],
                    "role": message["role"],
                    "content": message["content"],
                    "attachments": message["attachments"],
                    "evidence_refs": message["evidence_refs"],
                }
                for message in messages
            ]
        }
        return json.dumps(json_data, indent=2, ensure_ascii=False)
    if input_mode == "DotCode Compression":
        dotcode_messages = [f"{message['role'][0]}: {to_dotcode(message['content'])} .." for message in messages]
        return " ".join(dotcode_messages)
    return "\n".join([f"{message['role']}: {message['content']}" for message in messages])

def extract_messages_from_conversation(convo):
    """Normalize, clean, and sort messages from a ChatGPT conversation object."""
    mapping = convo.get("mapping", {})
    messages = []
    for item in mapping.values():
        msg = item.get("message")
        if msg and msg.get("content"):
            ts = msg.get("create_time")
            role = msg["author"]["role"].upper()
            text, attachments, evidence_refs = extract_content_text(msg["content"])
            if text:
                messages.append({
                    "timestamp": ts,
                    "role": role,
                    "content": text,
                    "attachments": attachments,
                    "evidence_refs": evidence_refs,
                })

    messages.sort(key=lambda x: x["timestamp"] if x["timestamp"] else 0)
    return messages

def get_ollama_models():
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=10)
        if response.status_code == 200:
            data = response.json()
            return [model["name"] for model in data.get("models", [])]
        else:
            return ["llama3", "mistral", "phi3:mini"]  # Fallback
    except requests.exceptions.RequestException:
        return ["llama3", "mistral", "phi3:mini"]  # Fallback

def render_app():
    """Render the Streamlit viewer UI."""
    st.title("Conversations JSON Viewer")

    uploaded_file = st.file_uploader("Upload conversations.json", type="json")

    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            titles = [convo.get("title", "Untitled") for convo in data if convo.get("title")]
            if titles:
                selected_title = st.selectbox("Select a conversation", titles)
                if selected_title:
                    for convo in data:
                        if convo.get("title") == selected_title:
                            st.header(f"=== Conversation: {convo['title']} ===")
                            st.write(f"Start: {ts_to_str(convo.get('create_time'))}")
                            st.write(f"End: {ts_to_str(convo.get('update_time'))}")
                            st.write("")

                            view_mode = st.radio("View Mode", ["Documentation", "Hierarchical"], index=0)
                            messages = extract_messages_from_conversation(convo)

                            file_stem = sanitize_filename(convo.get("title", "Untitled"))
                            raw_conversation_json = json.dumps(convo, indent=2, ensure_ascii=False)
                            thread_export_json = json.dumps(build_thread_export(convo, messages), indent=2, ensure_ascii=False)
                            evidence_manifest = build_evidence_manifest(convo, messages)
                            evidence_manifest_json = json.dumps(evidence_manifest, indent=2, ensure_ascii=False)
                            transcript_markdown = build_markdown_transcript(convo, messages)
                            project_memory_markdown = build_project_memory_markdown(convo, messages, evidence_manifest)

                            st.subheader("Export Selected Conversation")
                            st.write("Download the selected thread as archival JSON, cleaned JSON, an evidence manifest, a readable transcript, or a layered project-memory source document.")
                            export_col1, export_col2 = st.columns(2)
                            with export_col1:
                                st.download_button(
                                    label="Download raw conversation JSON",
                                    data=raw_conversation_json,
                                    file_name=f"{file_stem}.raw.json",
                                    mime="application/json",
                                    key=f"download_raw_{file_stem}"
                                )
                            with export_col2:
                                st.download_button(
                                    label="Download thread messages JSON",
                                    data=thread_export_json,
                                    file_name=f"{file_stem}.thread.json",
                                    mime="application/json",
                                    key=f"download_thread_{file_stem}"
                                )
                            export_col3, export_col4 = st.columns(2)
                            with export_col3:
                                st.download_button(
                                    label="Download evidence manifest JSON",
                                    data=evidence_manifest_json,
                                    file_name=f"{file_stem}.evidence_manifest.json",
                                    mime="application/json",
                                    key=f"download_evidence_{file_stem}"
                                )
                            with export_col4:
                                st.download_button(
                                    label="Download clean transcript MD",
                                    data=transcript_markdown,
                                    file_name=f"{file_stem}.transcript.md",
                                    mime="text/markdown",
                                    key=f"download_transcript_{file_stem}"
                                )
                            export_col5, export_col6 = st.columns(2)
                            with export_col5:
                                st.download_button(
                                    label="Download legal project memory MD",
                                    data=project_memory_markdown,
                                    file_name=f"{file_stem}.project_memory.md",
                                    mime="text/markdown",
                                    key=f"download_memory_{file_stem}"
                                )
                            with export_col6:
                                st.caption(f"Extracted exhibits: {evidence_manifest['evidence_count']}")

                            if view_mode == "Documentation":
                                for i, message in enumerate(messages, 1):
                                    st.markdown(f"**[{i}] {ts_to_str(message['timestamp'])} {message['role']}:** {message['content']}")
                                    st.write("")
                            elif view_mode == "Hierarchical":
                                for i, message in enumerate(messages, 1):
                                    with st.expander(f"[{i}] {ts_to_str(message['timestamp'])} {message['role']}"):
                                        st.write(message['content'])

                            st.subheader("AI Actions with Ollama")
                            st.write("Ensure Ollama is running locally (ollama serve) and you have models installed.")
                            if st.button("Test Ollama Connection"):
                                try:
                                    response = requests.get("http://localhost:11434/api/tags", timeout=10)
                                    st.write(f"Connection successful: Status {response.status_code}")
                                    data = response.json()
                                    models = [m["name"] for m in data.get("models", [])]
                                    st.write(f"Available models: {models}")
                                except Exception as e:
                                    st.error(f"Connection failed: {e}")
                            available_models = get_ollama_models()
                            model = st.selectbox("Select Model", available_models, help="Choose an installed Ollama model.")
                            input_mode = st.selectbox("Input Mode", ["Full Conversation", "Last 20 Messages", "Smart Summary (first 3 + last 10)", "JSON Structure", "DotCode Compression"], help="Limit input to avoid long prompts.")
                            default_prompt = {
                                "Full Conversation": "Summarize this conversation:\n{full_text}",
                                "Last 20 Messages": "Summarize this conversation:\n{full_text}",
                                "Smart Summary (first 3 + last 10)": "Summarize this conversation:\n{full_text}",
                                "JSON Structure": "Summarize this conversation based on the JSON structure:\n{full_text}",
                                "DotCode Compression": "This is a compressed conversation using a code similar to shorthand or Morse. Rules: Remove common words (the, and, is), keep consonants + syllable dots (1-3 dots per syllable). Example: 'The strawberry is juicy' → 'str... jcy.'. Sentences end with '..'. Decode and summarize this DotCode conversation:\n{full_text}"
                            }
                            prompt_template = st.text_area("Prompt", default_prompt[input_mode], help="Use {full_text} as placeholder for the conversation content.")
                            full_text_manual = build_full_text(messages, input_mode)
                            prompt_manual = prompt_template.replace("{full_text}", full_text_manual)

                            st.subheader("Manual AI Run (Bypass HTTP)")
                            st.write("For slow machines, download the prompt and run locally:")
                            st.download_button(
                                label="Download Prompt as .txt",
                                data=prompt_manual,
                                file_name=f"prompt_{selected_title.replace(' ', '_')}.txt",
                                mime="text/plain",
                                key="download_prompt"
                            )
                            st.write("Then, in terminal: `ollama run [model] < prompt.txt` (replace [model] with your choice, e.g., smollm:135m)")
                            st.write("Or, for short prompts: `ollama run [model] '[paste prompt]'`")

                            if st.button("Run AI on Thread"):
                                full_text = build_full_text(messages, input_mode)
                                prompt = prompt_template.replace("{full_text}", full_text)
                                st.write(f"Debug: Using model '{model}', input mode '{input_mode}'")
                                st.write(f"Debug: Prompt length: {len(prompt)} characters")
                                with st.expander("Show Full Prompt"):
                                    st.code(prompt, language="text")
                                try:
                                    response = requests.post("http://localhost:11434/api/generate", json={"model": model, "prompt": prompt, "stream": False}, timeout=120)
                                    st.write(f"Debug: Status {response.status_code}")
                                    st.write(f"Debug: Response text: {response.text[:500]}")
                                    if response.status_code == 200:
                                        data = response.json()
                                        result = data.get("response", "No response in JSON")
                                        st.success("AI Response:")
                                        st.write(result)
                                    else:
                                        st.error(f"Ollama error: {response.status_code} - {response.text}")
                                except requests.exceptions.RequestException as e:
                                    st.error(f"Failed to connect to Ollama: {e}. Make sure Ollama is running on localhost:11434.")

                            break
            else:
                st.error("No conversations with titles found in the file.")
        except json.JSONDecodeError:
            st.error("Invalid JSON file.")
    else:
        st.info("Please upload a conversations.json file to get started.")


if __name__ == "__main__":
    render_app()