import streamlit as st
import json
import requests
import re
from datetime import datetime

stop_words = set("the and is in to a an for with on at by from as or but not this that it be have do will can".split())

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

                        mapping = convo.get("mapping", {})
                        messages = []
                        for m in mapping.values():
                            msg = m.get("message")
                            if msg and msg.get("content"):
                                ts = msg.get("create_time")
                                role = msg["author"]["role"].upper()
                                parts = msg["content"].get("parts", [])
                                text = normalize_parts(parts)
                                if text:  # only include non-empty messages
                                    messages.append((ts, role, text))

                        messages.sort(key=lambda x: x[0] if x[0] else 0)

                        if view_mode == "Documentation":
                            for i, (ts, role, text) in enumerate(messages, 1):
                                st.markdown(f"**[{i}] {ts_to_str(ts)} {role}:** {text}")
                                st.write("")  # Add spacing
                        elif view_mode == "Hierarchical":
                            for i, (ts, role, text) in enumerate(messages, 1):
                                with st.expander(f"[{i}] {ts_to_str(ts)} {role}"):
                                    st.write(text)

                        # AI Actions Section
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
                        
                        # Construct full_text and prompt for manual download
                        if input_mode == "Full Conversation":
                            full_text_manual = "\n".join([f"{role}: {text}" for ts, role, text in messages])
                        elif input_mode == "Last 20 Messages":
                            recent_messages = messages[-20:]
                            full_text_manual = "\n".join([f"{role}: {text}" for ts, role, text in recent_messages])
                        elif input_mode == "Smart Summary (first 3 + last 10)":
                            first_3 = messages[:3]
                            last_10 = messages[-10:]
                            summary_messages = first_3 + last_10
                            full_text_manual = "\n".join([f"{role}: {text}" for ts, role, text in summary_messages])
                        elif input_mode == "JSON Structure":
                            json_data = {"messages": [{"timestamp": ts, "role": role, "content": text} for ts, role, text in messages]}
                            full_text_manual = json.dumps(json_data, indent=2)
                        elif input_mode == "DotCode Compression":
                            dotcode_messages = [f"{role[0]}: {to_dotcode(text)} .." for ts, role, text in messages]
                            full_text_manual = ' '.join(dotcode_messages)
                        prompt_manual = prompt_template.replace("{full_text}", full_text_manual)
                        
                        # Manual AI Run Section
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
                            if input_mode == "Full Conversation":
                                full_text = "\n".join([f"{role}: {text}" for ts, role, text in messages])
                            elif input_mode == "Last 20 Messages":
                                recent_messages = messages[-20:]
                                full_text = "\n".join([f"{role}: {text}" for ts, role, text in recent_messages])
                            elif input_mode == "Smart Summary (first 3 + last 10)":
                                first_3 = messages[:3]
                                last_10 = messages[-10:]
                                summary_messages = first_3 + last_10
                                full_text = "\n".join([f"{role}: {text}" for ts, role, text in summary_messages])
                            elif input_mode == "JSON Structure":
                                json_data = {"messages": [{"timestamp": ts, "role": role, "content": text} for ts, role, text in messages]}
                                full_text = json.dumps(json_data, indent=2)
                            elif input_mode == "DotCode Compression":
                                dotcode_messages = [f"{role[0]}: {to_dotcode(text)} .." for ts, role, text in messages]
                                full_text = ' '.join(dotcode_messages)
                            prompt = prompt_template.replace("{full_text}", full_text)
                            st.write(f"Debug: Using model '{model}', input mode '{input_mode}'")
                            st.write(f"Debug: Prompt length: {len(prompt)} characters")
                            with st.expander("Show Full Prompt"):
                                st.code(prompt, language="text")
                            try:
                                response = requests.post("http://localhost:11434/api/generate", json={"model": model, "prompt": prompt, "stream": False}, timeout=120)
                                st.write(f"Debug: Status {response.status_code}")
                                st.write(f"Debug: Response text: {response.text[:500]}")  # First 500 chars
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