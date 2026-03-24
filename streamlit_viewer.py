import json
import io
import requests
import re
import zipfile
from datetime import datetime

try:
    import streamlit as st
except ImportError:
    st = None

stop_words = set("the and is in to a an for with on at by from as or but not this that it be have do will can".split())
MARKDOWN_IMAGE_RE = re.compile(r'!\[(?P<alt>[^\]]*)\]\((?P<url>[^)]+)\)')
FILE_ID_RE = re.compile(r'(file_[A-Za-z0-9]+)')
SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])\s+|\n+')
INTIMATE_CONTENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bsexual(?:ly)?\b",
        r"\bintimate(?:ly)?\b",
        r"\bnude|naked\b",
        r"\bkiss(?:ed|ing)?\b",
        r"\baffair\b",
        r"\bromantic\b",
        r"\bexplicit\b",
        r"\bbodily\b",
    ]
]
DATE_REFERENCE_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{1,2}/\d{1,2}/\d{2,4}|20\d{2})\b",
    re.IGNORECASE,
)
LEGAL_HIGH_WEIGHT_PATTERNS = {
    "court_order": re.compile(r"\b(court|order|decree|mandate|hearing|motion|filing|compliance|noncompliance)\b", re.IGNORECASE),
    "property_dispute": re.compile(r"\b(property|sale|listing|showing|realtor|lockbox|mortgage|insurance|contractor)\b", re.IGNORECASE),
    "evidence": re.compile(r"\b(evidence|photo|screenshot|attachment|proof|exhibit|document)\b", re.IGNORECASE),
    "dispute_actor": re.compile(r"\b(attorney|counsel|judge|lender|insurer|opposing|party|broker|commissioner)\b", re.IGNORECASE),
}
LEGAL_MEDIUM_WEIGHT_PATTERNS = {
    "strategy": re.compile(r"\b(strategy|argument|position|remedy|settlement|risk|timeline|chronology|deadline|obligation|duty)\b", re.IGNORECASE),
    "context": re.compile(r"\b(schedule|money|payment|expense|damage|repair|access|communication|response)\b", re.IGNORECASE),
    "emotion_tied_to_case": re.compile(r"\b(stress|pressure|afraid|angry|panic|overwhelmed)\b", re.IGNORECASE),
}
LEGAL_NEGATIVE_PATTERNS = {
    "software": re.compile(r"\b(code|coding|python|streamlit|debug|repo|commit|pull request|ui|json parser)\b", re.IGNORECASE),
    "creative": re.compile(r"\b(song|music|poem|story|novel|creative writing|lyrics)\b", re.IGNORECASE),
    "general_life": re.compile(r"\b(recipe|shopping|vacation|restaurant|birthday|workout|movie|game|hobby)\b", re.IGNORECASE),
}

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

def split_into_sentences(text):
    """Split freeform text into compact sentence-like segments."""
    if not text:
        return []
    return [" ".join(part.split()).strip() for part in SENTENCE_SPLIT_RE.split(text) if " ".join(part.split()).strip()]

def collect_salient_terms(messages, limit=8):
    """Extract lightweight keywords to describe the thread at a glance."""
    counts = {}
    for message in messages:
        for token in re.findall(r"\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b", message["content"].lower()):
            if token in stop_words:
                continue
            if token in {"user", "assistant", "attachment", "referenced", "image", "file", "uploaded"}:
                continue
            counts[token] = counts.get(token, 0) + 1

    ranked_terms = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _count in ranked_terms[:limit]]

def extract_structured_points(messages, limit=5):
    """Pull out notable statements, decisions, and questions for top-layer summaries."""
    key_points = []
    decisions = []
    open_questions = []
    next_actions = []

    for index, message in enumerate(messages, 1):
        sentences = split_into_sentences(message["content"])
        for sentence in sentences:
            if len(sentence) < 25:
                continue

            lowered = sentence.lower()
            entry = f"[{index}] {message['role'].title()}: {summarize_text(sentence, 180)}"

            if len(key_points) < limit and entry not in key_points:
                key_points.append(entry)

            if "?" in sentence and len(open_questions) < limit and entry not in open_questions:
                open_questions.append(entry)

            if any(keyword in lowered for keyword in ["decide", "decision", "agreed", "plan", "priority", "goal", "conclusion"]):
                if len(decisions) < limit and entry not in decisions:
                    decisions.append(entry)

            if any(keyword in lowered for keyword in ["next", "follow up", "need to", "must", "should", "action", "todo"]):
                if len(next_actions) < limit and entry not in next_actions:
                    next_actions.append(entry)

    return key_points[:limit], decisions[:limit], open_questions[:limit], next_actions[:limit]

def build_thread_summary(convo, messages, evidence_manifest):
    """Create a concise top-layer summary for reuse in ChatGPT Projects or local summarizers."""
    participants = sorted({message["role"].title() for message in messages})
    message_count = len(messages)
    evidence_count = evidence_manifest["evidence_count"]
    user_messages = [message for message in messages if message["role"] == "USER"]
    assistant_messages = [message for message in messages if message["role"] == "ASSISTANT"]
    salient_terms = collect_salient_terms(messages)
    key_points, decisions, open_questions, next_actions = extract_structured_points(messages)

    first_user = summarize_text(user_messages[0]["content"], 180) if user_messages else "No user-authored message found."
    last_assistant = summarize_text(assistant_messages[-1]["content"], 180) if assistant_messages else "No assistant-authored reply found."

    executive_summary = (
        f"Thread '{convo.get('title', 'Untitled')}' spans {message_count} messages between "
        f"{', '.join(participants) or 'unknown participants'}. "
        f"The opening user context is: {first_user} "
        f"The latest assistant position is: {last_assistant} "
        f"The thread contains {evidence_count} explicit evidence reference(s)."
    )

    return {
        "title": convo.get("title", "Untitled"),
        "create_time": convo.get("create_time"),
        "update_time": convo.get("update_time"),
        "message_count": message_count,
        "participants": participants,
        "evidence_count": evidence_count,
        "salient_terms": salient_terms,
        "executive_summary": executive_summary,
        "key_points": key_points,
        "decisions": decisions,
        "open_questions": open_questions,
        "next_actions": next_actions,
        "timeline_anchors": build_timeline_anchors(messages, limit=8),
    }

def build_thread_summary_markdown(convo, messages, evidence_manifest):
    """Create a higher-level markdown summary suitable for seeding downstream chats."""
    summary = build_thread_summary(convo, messages, evidence_manifest)

    def bulletize(items, fallback):
        if not items:
            return [f"- {fallback}"]
        return [f"- {item}" for item in items]

    timeline_lines = summary["timeline_anchors"] if summary["timeline_anchors"] else ["- No timeline anchors available."]

    lines = [
        f"# Thread Summary: {summary['title']}",
        "",
        "## Executive Summary",
        f"- {summary['executive_summary']}",
        "",
        "## Thread Metadata",
        f"- Start: {ts_to_str(summary['create_time'])}",
        f"- End: {ts_to_str(summary['update_time'])}",
        f"- Participants: {', '.join(summary['participants']) or 'Unknown'}",
        f"- Message count: {summary['message_count']}",
        f"- Evidence references: {summary['evidence_count']}",
        f"- Salient terms: {', '.join(summary['salient_terms']) if summary['salient_terms'] else 'None extracted'}",
        "",
        "## Key Points",
        *bulletize(summary["key_points"], "No key points were extracted automatically."),
        "",
        "## Decisions Or Working Conclusions",
        *bulletize(summary["decisions"], "No explicit decisions were detected."),
        "",
        "## Open Questions",
        *bulletize(summary["open_questions"], "No open questions were detected."),
        "",
        "## Next Actions",
        *bulletize(summary["next_actions"], "No clear next actions were detected."),
        "",
        "## Timeline Anchors",
        *timeline_lines,
        "",
        "## Retrieval Handoff",
        "- Use this summary as the top layer for ChatGPT Projects or downstream chat context.",
        "- If the answer needs detail, descend next to the clean transcript.",
        "- If the answer needs proof, descend to the evidence manifest and original export assets.",
    ]
    return "\n".join(lines).strip() + "\n"

def build_summary_refinement_prompt(summary_markdown, refinement_mode):
    """Create an Ollama prompt that rewrites the deterministic summary into a tighter handoff artifact."""
    mode_instructions = {
        "Executive Brief": (
            "Rewrite the summary into a compact executive brief for a ChatGPT Project. "
            "Keep only durable facts, current objective, major decisions, open questions, and next actions. "
            "Prefer crisp bullets over narrative."
        ),
        "Project Memory Seed": (
            "Rewrite the summary into a durable project-memory seed. "
            "Organize it as: matter summary, durable facts, active issues, evidence posture, open questions, and next actions. "
            "Preserve retrieval guidance when it matters."
        ),
        "Chronology Focus": (
            "Rewrite the summary with chronology first. "
            "Emphasize sequence, changes in direction, decisions, deadlines, and unresolved follow-ups. "
            "Keep the output concise and suitable for downstream retrieval."
        ),
    }
    instruction = mode_instructions.get(refinement_mode, mode_instructions["Executive Brief"])
    return (
        "You are refining a deterministic conversation summary into a higher-quality retrieval handoff.\n\n"
        f"Task: {instruction}\n\n"
        "Requirements:\n"
        "- Do not invent facts that are not present in the source summary.\n"
        "- Preserve uncertainty where the source is uncertain.\n"
        "- Keep references to evidence or retrieval layers when they matter.\n"
        "- Use Markdown.\n"
        "- Prefer short sections and bullets.\n\n"
        "Source summary:\n"
        f"{summary_markdown}"
    )

def run_ollama_prompt(model, prompt, timeout=120):
    """Execute a non-streaming Ollama generation call and return the response text."""
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("response", "").strip()

def refinement_session_key(file_stem):
    """Create a stable Streamlit session-state key for refined summaries."""
    return f"refined_summary::{file_stem}"

def build_refinement_label(model, refinement_mode):
    """Describe which model and prompt mode produced a refined summary."""
    return f"Refined via Ollama: {model} | Mode: {refinement_mode}"

def filter_for_general_audience(text):
    """Redact intimate details from derived summary text without altering raw source exports."""
    filtered_lines = []
    for line in text.splitlines():
        updated = line
        for pattern in INTIMATE_CONTENT_PATTERNS:
            updated = pattern.sub("[redacted intimate detail]", updated)
        updated = re.sub(r"(?:\[redacted intimate detail\][ ,;:]*){2,}", "[redacted intimate detail] ", updated)
        filtered_lines.append(updated)
    return "\n".join(filtered_lines)

def apply_content_filter(text, filter_mode):
    """Apply an opt-in content filter to top-layer derived outputs."""
    if filter_mode == "General Audience":
        return filter_for_general_audience(text)
    return text

def score_legal_relevance(text, evidence_refs=None):
    """Score message text for legal relevance using weighted heuristic features."""
    evidence_refs = evidence_refs or []
    matched_high = sorted(label for label, pattern in LEGAL_HIGH_WEIGHT_PATTERNS.items() if pattern.search(text))
    matched_medium = sorted(label for label, pattern in LEGAL_MEDIUM_WEIGHT_PATTERNS.items() if pattern.search(text))
    matched_negative = sorted(label for label, pattern in LEGAL_NEGATIVE_PATTERNS.items() if pattern.search(text))
    has_date_reference = bool(DATE_REFERENCE_RE.search(text))

    score = len(matched_high) * 4 + len(matched_medium) * 2 - len(matched_negative) * 4
    if has_date_reference and (matched_high or matched_medium):
        score += 2
    if evidence_refs:
        score += 2

    if matched_high and matched_negative and score < 8:
        classification = "uncertain"
    elif score >= 8 or (len(matched_high) >= 2 and score >= 6):
        classification = "legal_core"
    elif score >= 3 or matched_high or len(matched_medium) >= 2:
        classification = "legal_adjacent"
    elif score <= -4 and not matched_high and not matched_medium:
        classification = "non_legal"
    else:
        classification = "uncertain"

    return {
        "score": score,
        "classification": classification,
        "matched_high": matched_high,
        "matched_medium": matched_medium,
        "matched_negative": matched_negative,
        "has_date_reference": has_date_reference,
        "has_evidence_refs": bool(evidence_refs),
    }

def summarize_message_ranges(indices):
    """Compactly describe contiguous message index ranges."""
    if not indices:
        return []

    ranges = []
    start = prev = indices[0]
    for value in indices[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = value
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ranges

def build_legal_relevance_manifest(convo, messages):
    """Classify a thread and its messages for legal-memory shaping."""
    classified_messages = []
    thread_score = 0
    counts = {"legal_core": 0, "legal_adjacent": 0, "non_legal": 0, "uncertain": 0}

    for index, message in enumerate(messages, 1):
        relevance = score_legal_relevance(message["content"], message["evidence_refs"])
        thread_score += relevance["score"]
        counts[relevance["classification"]] += 1
        classified_messages.append({
            "message_index": index,
            "timestamp": message["timestamp"],
            "role": message["role"].lower(),
            "classification": relevance["classification"],
            "score": relevance["score"],
            "matched_high": relevance["matched_high"],
            "matched_medium": relevance["matched_medium"],
            "matched_negative": relevance["matched_negative"],
            "has_date_reference": relevance["has_date_reference"],
            "has_evidence_refs": relevance["has_evidence_refs"],
            "excerpt": summarize_text(message["content"], 220),
        })

    included_indices = [
        item["message_index"]
        for item in classified_messages
        if item["classification"] in {"legal_core", "legal_adjacent"}
    ]
    range_summary = summarize_message_ranges(included_indices)
    mixed_domain = bool((counts["legal_core"] or counts["legal_adjacent"]) and counts["non_legal"])

    if counts["legal_core"] >= 2 or thread_score >= 18:
        thread_classification = "legal_core" if not mixed_domain else "uncertain"
    elif counts["legal_core"] or counts["legal_adjacent"]:
        thread_classification = "legal_adjacent" if not mixed_domain else "uncertain"
    elif counts["non_legal"] and not counts["uncertain"]:
        thread_classification = "non_legal"
    else:
        thread_classification = "uncertain"

    return {
        "conversation_title": convo.get("title", "Untitled"),
        "thread_classification": thread_classification,
        "thread_score": thread_score,
        "mixed_domain": mixed_domain,
        "message_counts": counts,
        "included_message_ranges": range_summary,
        "included_message_count": len(included_indices),
        "messages": classified_messages,
    }

def collect_legal_sentences(messages, allowed_indices, predicate, limit=5):
    """Extract traceable sentences from selected legal-relevant messages."""
    collected = []
    seen = set()
    allowed = set(allowed_indices)

    for index, message in enumerate(messages, 1):
        if index not in allowed:
            continue
        for sentence in split_into_sentences(message["content"]):
            if len(sentence) < 20:
                continue
            if not predicate(sentence):
                continue
            normalized = sentence.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            collected.append(f"- [msg {index}] {summarize_text(sentence, 220)}")
            if len(collected) >= limit:
                return collected
    return collected

def build_legal_memory_markdown(convo, messages, evidence_manifest, relevance_manifest):
    """Create a legal-specific memory artifact from mixed-domain threads."""
    included_indices = [
        item["message_index"]
        for item in relevance_manifest["messages"]
        if item["classification"] in {"legal_core", "legal_adjacent"}
    ]
    uncertain_indices = [
        item["message_index"]
        for item in relevance_manifest["messages"]
        if item["classification"] == "uncertain"
    ]
    included_messages = [messages[index - 1] for index in included_indices]
    uncertain_messages = [messages[index - 1] for index in uncertain_indices]
    evidence_by_message = {}
    for exhibit in evidence_manifest["exhibits"]:
        evidence_by_message.setdefault(exhibit["message_index"], []).append(exhibit)

    if included_messages:
        matter_summary = [
            f"- Thread classification: {relevance_manifest['thread_classification']} (score={relevance_manifest['thread_score']}).",
            f"- Included legal-relevant message ranges: {', '.join(relevance_manifest['included_message_ranges']) or 'none identified' }.",
            f"- Matter focus: {summarize_text(included_messages[0]['content'], 220)}",
        ]
    else:
        matter_summary = [
            "- No legal-core or legal-adjacent message spans were identified in this thread.",
            f"- Thread classification: {relevance_manifest['thread_classification']} (score={relevance_manifest['thread_score']}).",
        ]

    durable_facts = collect_legal_sentences(
        messages,
        included_indices,
        lambda sentence: not sentence.endswith("?") and (DATE_REFERENCE_RE.search(sentence) or any(pattern.search(sentence) for pattern in LEGAL_HIGH_WEIGHT_PATTERNS.values())),
        limit=6,
    ) or ["- No durable facts were extracted with confidence from the included legal spans."]

    governing_orders = collect_legal_sentences(
        messages,
        included_indices,
        lambda sentence: re.search(r"\b(order|ordered|must|shall|required|deadline|duty|hearing|motion|decree|compliance)\b", sentence, re.IGNORECASE) is not None,
        limit=5,
    ) or ["- No governing orders or duties were detected in the included legal spans."]

    evidence_highlights = []
    for message_index in included_indices:
        for exhibit in evidence_by_message.get(message_index, []):
            evidence_highlights.append(
                f"- {exhibit['exhibit_id']} [msg {message_index}] {exhibit['kind']} | {exhibit['label']} | {exhibit['retrieval_note']}"
            )
    if not evidence_highlights:
        evidence_highlights = ["- No evidence references were attached to the included legal spans."]

    timeline_anchors = [
        f"- {ts_to_str(message['timestamp'])} [msg {index}] {message['role']}: {summarize_text(message['content'], 160)}"
        for index, message in enumerate(messages, 1)
        if index in set(included_indices)
    ][:8] or ["- No legal timeline anchors were selected."]

    contradictions = collect_legal_sentences(
        messages,
        included_indices,
        lambda sentence: re.search(r"\b(contradict|however|but|inconsistent|changed|excuse|failed|refused|did not|didn't|not true)\b", sentence, re.IGNORECASE) is not None,
        limit=5,
    ) or ["- No contradiction or pattern evidence was extracted with confidence."]

    current_posture = [
        f"- [msg {item['message_index']}] {messages[item['message_index'] - 1]['role'].title()}: {item['excerpt']}"
        for item in relevance_manifest['messages']
        if item['message_index'] in set(included_indices)
    ][-3:] or ["- Current posture could not be derived because no legal-relevant spans were included."]

    open_questions = collect_legal_sentences(
        messages,
        included_indices,
        lambda sentence: sentence.endswith("?") or "?" in sentence,
        limit=5,
    ) or ["- No open legal questions were detected in the included spans."]

    _key_points, _decisions, _questions, next_actions_raw = extract_structured_points(included_messages)
    next_actions = [f"- {item}" for item in next_actions_raw[:5]] or ["- No concrete next actions were extracted from the included legal spans."]

    uncertain_notes = [
        f"- [msg {item['message_index']}] Possible contextual relevance only: {item['excerpt']}"
        for item in relevance_manifest['messages']
        if item['message_index'] in set(uncertain_indices)
    ][:5]
    if not uncertain_notes and uncertain_messages:
        uncertain_notes = [
            f"- [msg {index}] Possible contextual relevance only: {summarize_text(message['content'], 220)}"
            for index, message in enumerate(messages, 1)
            if index in set(uncertain_indices)
        ][:5]

    source_scope_notes = [
        f"- Source thread classification: {relevance_manifest['thread_classification']}.",
        f"- Mixed-domain thread: {'yes' if relevance_manifest['mixed_domain'] else 'no'}.",
        f"- Included message ranges: {', '.join(relevance_manifest['included_message_ranges']) or 'none'}.",
        f"- Omitted counts: non_legal={relevance_manifest['message_counts']['non_legal']}, uncertain={relevance_manifest['message_counts']['uncertain']}",
        "- Important facts should be traced back through the cited message indices and evidence IDs before downstream reuse.",
    ]
    if uncertain_notes:
        source_scope_notes.extend([
            "- Uncertain spans were excluded from the main legal sections and retained only as possible contextual relevance:",
            *uncertain_notes,
        ])

    lines = [
        f"# Legal Memory Artifact: {convo.get('title', 'Untitled')}",
        "",
        "## Matter Summary",
        *matter_summary,
        "",
        "## Durable Facts",
        *durable_facts,
        "",
        "## Governing Orders / Duties",
        *governing_orders,
        "",
        "## Evidence Highlights",
        *evidence_highlights,
        "",
        "## Timeline Anchors",
        *timeline_anchors,
        "",
        "## Contradictions / Pattern Evidence",
        *contradictions,
        "",
        "## Current Posture",
        *current_posture,
        "",
        "## Open Questions",
        *open_questions,
        "",
        "## Next Actions",
        *next_actions,
        "",
        "## Source Scope / Notes",
        *source_scope_notes,
    ]
    return "\n".join(lines).strip() + "\n"

def build_legal_timeline_json(convo, messages, evidence_manifest, relevance_manifest):
    """Create a structured chronology export from legal-core and legal-adjacent spans."""
    included_indices = {
        item["message_index"]
        for item in relevance_manifest["messages"]
        if item["classification"] in {"legal_core", "legal_adjacent"}
    }
    evidence_by_message = {}
    for exhibit in evidence_manifest["exhibits"]:
        evidence_by_message.setdefault(exhibit["message_index"], []).append(exhibit)

    events = []
    for index, message in enumerate(messages, 1):
        if index not in included_indices:
            continue

        message_relevance = next(
            (item for item in relevance_manifest["messages"] if item["message_index"] == index),
            None,
        )
        event_type = "evidence_reference" if message["evidence_refs"] else "statement"
        if message_relevance and message_relevance["has_date_reference"]:
            event_type = "dated_event"
        if message_relevance and any(label in {"court_order", "property_dispute"} for label in message_relevance["matched_high"]):
            event_type = "obligation_or_dispute"

        events.append({
            "message_index": index,
            "timestamp": message["timestamp"],
            "timestamp_text": ts_to_str(message["timestamp"]),
            "role": message["role"].lower(),
            "classification": message_relevance["classification"] if message_relevance else "unknown",
            "event_type": event_type,
            "summary": summarize_text(message["content"], 220),
            "matched_high": message_relevance["matched_high"] if message_relevance else [],
            "matched_medium": message_relevance["matched_medium"] if message_relevance else [],
            "evidence_ids": [exhibit["exhibit_id"] for exhibit in evidence_by_message.get(index, [])],
        })

    return {
        "conversation_title": convo.get("title", "Untitled"),
        "thread_classification": relevance_manifest["thread_classification"],
        "included_message_ranges": relevance_manifest["included_message_ranges"],
        "event_count": len(events),
        "events": events,
    }

def build_batch_summary_zip(conversations, filter_mode="Original"):
    """Create a ZIP archive with deterministic thread summaries for all titled conversations."""
    buffer = io.BytesIO()
    manifest = []

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for convo in conversations:
            title = convo.get("title")
            if not title:
                continue

            file_stem = sanitize_filename(title)
            messages = extract_messages_from_conversation(convo)
            evidence_manifest = build_evidence_manifest(convo, messages)
            summary_markdown = apply_content_filter(
                build_thread_summary_markdown(convo, messages, evidence_manifest),
                filter_mode,
            )

            archive.writestr(f"summaries/{file_stem}.summary.md", summary_markdown)
            manifest.append({
                "title": title,
                "file_name": f"summaries/{file_stem}.summary.md",
                "message_count": len(messages),
                "evidence_count": evidence_manifest["evidence_count"],
                "create_time": convo.get("create_time"),
                "update_time": convo.get("update_time"),
                "filter_mode": filter_mode,
            })

        archive.writestr(
            "summaries/manifest.json",
            json.dumps({"conversation_count": len(manifest), "summaries": manifest}, indent=2, ensure_ascii=False),
        )

    return buffer.getvalue()

def build_batch_legal_memory_zip(conversations):
    """Create a ZIP archive with legal-memory artifacts and relevance manifests for all titled conversations."""
    buffer = io.BytesIO()
    manifest = []

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for convo in conversations:
            title = convo.get("title")
            if not title:
                continue

            file_stem = sanitize_filename(title)
            messages = extract_messages_from_conversation(convo)
            evidence_manifest = build_evidence_manifest(convo, messages)
            legal_relevance_manifest = build_legal_relevance_manifest(convo, messages)
            legal_memory_markdown = build_legal_memory_markdown(convo, messages, evidence_manifest, legal_relevance_manifest)
            legal_timeline_json = build_legal_timeline_json(convo, messages, evidence_manifest, legal_relevance_manifest)

            archive.writestr(
                f"legal_relevance/{file_stem}.legal_relevance.json",
                json.dumps(legal_relevance_manifest, indent=2, ensure_ascii=False),
            )
            archive.writestr(
                f"legal_timeline/{file_stem}.timeline.json",
                json.dumps(legal_timeline_json, indent=2, ensure_ascii=False),
            )

            thread_classification = legal_relevance_manifest["thread_classification"]
            export_status = "skipped_non_legal"
            exported_files = [
                f"legal_relevance/{file_stem}.legal_relevance.json",
                f"legal_timeline/{file_stem}.timeline.json",
            ]

            if thread_classification in {"legal_core", "legal_adjacent", "uncertain"}:
                archive.writestr(f"legal_memory/{file_stem}.legal_memory.md", legal_memory_markdown)
                exported_files.append(f"legal_memory/{file_stem}.legal_memory.md")
                export_status = "exported"

            manifest.append({
                "title": title,
                "thread_classification": thread_classification,
                "thread_score": legal_relevance_manifest["thread_score"],
                "mixed_domain": legal_relevance_manifest["mixed_domain"],
                "included_message_ranges": legal_relevance_manifest["included_message_ranges"],
                "included_message_count": legal_relevance_manifest["included_message_count"],
                "export_status": export_status,
                "files": exported_files,
            })

        archive.writestr(
            "legal_memory/manifest.json",
            json.dumps({"conversation_count": len(manifest), "threads": manifest}, indent=2, ensure_ascii=False),
        )

    return buffer.getvalue()

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
    if st is None:
        raise RuntimeError("streamlit is required to render the UI. Install it with: pip install streamlit")

    st.title("Conversations JSON Viewer")

    uploaded_file = st.file_uploader("Upload conversations.json", type="json")

    if uploaded_file is not None:
        try:
            data = json.load(uploaded_file)
            titles = [convo.get("title", "Untitled") for convo in data if convo.get("title")]
            if titles:
                content_filter_mode = st.selectbox(
                    "Content Filter",
                    ["Original", "General Audience"],
                    help="Apply this only to derived summary outputs. Raw JSON, transcript fidelity, and evidence references remain unchanged.",
                )
                batch_summary_zip = build_batch_summary_zip(data, filter_mode=content_filter_mode)
                batch_legal_memory_zip = build_batch_legal_memory_zip(data)

                st.subheader("Batch Summary Export")
                st.write("Generate deterministic summary files for every titled conversation in this upload.")
                st.caption(f"Batch summaries will use content filter: {content_filter_mode}")
                batch_col1, batch_col2 = st.columns(2)
                with batch_col1:
                    st.download_button(
                        label="Download all thread summaries ZIP",
                        data=batch_summary_zip,
                        file_name="chatgpt_thread_summaries.zip",
                        mime="application/zip",
                        key="download_all_summaries_zip"
                    )
                with batch_col2:
                    st.download_button(
                        label="Download all legal memory ZIP",
                        data=batch_legal_memory_zip,
                        file_name="chatgpt_legal_memory.zip",
                        mime="application/zip",
                        key="download_all_legal_memory_zip"
                    )

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
                            legal_relevance_manifest = build_legal_relevance_manifest(convo, messages)
                            legal_relevance_manifest_json = json.dumps(legal_relevance_manifest, indent=2, ensure_ascii=False)
                            legal_timeline = build_legal_timeline_json(convo, messages, evidence_manifest, legal_relevance_manifest)
                            legal_timeline_json = json.dumps(legal_timeline, indent=2, ensure_ascii=False)
                            transcript_markdown = build_markdown_transcript(convo, messages)
                            thread_summary_markdown = apply_content_filter(
                                build_thread_summary_markdown(convo, messages, evidence_manifest),
                                content_filter_mode,
                            )
                            project_memory_markdown = build_project_memory_markdown(convo, messages, evidence_manifest)
                            legal_memory_markdown = build_legal_memory_markdown(convo, messages, evidence_manifest, legal_relevance_manifest)
                            refined_summary_key = refinement_session_key(file_stem)
                            refined_summary_payload = st.session_state.get(refined_summary_key)

                            st.subheader("Export Selected Conversation")
                            st.write("Download the selected thread as archival JSON, cleaned JSON, an evidence manifest, a high-level thread summary, a readable transcript, or a layered project-memory source document.")
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
                                    label="Download thread summary MD",
                                    data=thread_summary_markdown,
                                    file_name=f"{file_stem}.summary.md",
                                    mime="text/markdown",
                                    key=f"download_summary_{file_stem}"
                                )
                            with export_col6:
                                st.download_button(
                                    label="Download legal project memory MD",
                                    data=project_memory_markdown,
                                    file_name=f"{file_stem}.project_memory.md",
                                    mime="text/markdown",
                                    key=f"download_memory_{file_stem}"
                                )
                            if refined_summary_payload:
                                export_col7, export_col8 = st.columns(2)
                                with export_col7:
                                    st.download_button(
                                        label="Download refined summary MD",
                                        data=refined_summary_payload["content"],
                                        file_name=f"{file_stem}.summary.refined.md",
                                        mime="text/markdown",
                                        key=f"download_refined_export_{file_stem}"
                                    )
                                with export_col8:
                                    st.caption(refined_summary_payload["label"])
                            export_col9, export_col10 = st.columns(2)
                            with export_col9:
                                st.download_button(
                                    label="Download legal relevance manifest JSON",
                                    data=legal_relevance_manifest_json,
                                    file_name=f"{file_stem}.legal_relevance.json",
                                    mime="application/json",
                                    key=f"download_legal_relevance_{file_stem}"
                                )
                            with export_col10:
                                st.download_button(
                                    label="Download legal memory artifact MD",
                                    data=legal_memory_markdown,
                                    file_name=f"{file_stem}.legal_memory.md",
                                    mime="text/markdown",
                                    key=f"download_legal_memory_{file_stem}"
                                )
                            export_col11, export_col12 = st.columns(2)
                            with export_col11:
                                st.download_button(
                                    label="Download legal timeline JSON",
                                    data=legal_timeline_json,
                                    file_name=f"{file_stem}.timeline.json",
                                    mime="application/json",
                                    key=f"download_legal_timeline_{file_stem}"
                                )
                            with export_col12:
                                st.caption(f"Timeline events: {legal_timeline['event_count']}")
                            summary_col1, summary_col2 = st.columns(2)
                            with summary_col1:
                                st.caption(f"Extracted exhibits: {evidence_manifest['evidence_count']}")
                            with summary_col2:
                                st.caption(f"Use the thread summary as the top-layer handoff to downstream LLMs. Filter: {content_filter_mode}")

                            legal_col1, legal_col2 = st.columns(2)
                            with legal_col1:
                                st.caption(
                                    f"Legal classification: {legal_relevance_manifest['thread_classification']} (score={legal_relevance_manifest['thread_score']})"
                                )
                            with legal_col2:
                                st.caption(
                                    f"Legal-relevant message ranges: {', '.join(legal_relevance_manifest['included_message_ranges']) or 'none'}"
                                )

                            with st.expander("Preview legal memory artifact", expanded=False):
                                st.markdown(legal_memory_markdown)

                            with st.expander("Preview legal relevance manifest", expanded=False):
                                st.code(legal_relevance_manifest_json, language="json")

                            with st.expander("Preview legal timeline JSON", expanded=False):
                                st.code(legal_timeline_json, language="json")

                            st.subheader("Summary Comparison")
                            comparison_col1, comparison_col2 = st.columns(2)
                            with comparison_col1:
                                st.caption("Deterministic Summary")
                                st.caption("Generated without an LLM.")
                                with st.expander("Preview deterministic summary", expanded=False):
                                    st.markdown(thread_summary_markdown)
                            with comparison_col2:
                                if refined_summary_payload:
                                    st.caption("Refined Summary")
                                    st.caption(refined_summary_payload["label"])
                                    with st.expander("Preview refined summary", expanded=True):
                                        st.markdown(refined_summary_payload["content"])
                                else:
                                    st.caption("Refined Summary")
                                    st.info("Run an Ollama refinement to compare it side by side with the deterministic summary.")

                            st.subheader("Refine Thread Summary with Ollama")
                            st.write("Rewrite the deterministic thread summary with a local model before sending it to ChatGPT Projects or another downstream system.")
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
                            model = st.selectbox("Refinement Model", available_models, help="Choose an installed Ollama model for summary rewriting.")
                            refinement_mode = st.selectbox(
                                "Summary Refinement Mode",
                                ["Executive Brief", "Project Memory Seed", "Chronology Focus"],
                                help="Each mode uses a different prompt template for the same source summary.",
                            )
                            refinement_prompt = build_summary_refinement_prompt(thread_summary_markdown, refinement_mode)
                            with st.expander("Show summary refinement prompt", expanded=False):
                                st.code(refinement_prompt, language="text")
                            st.download_button(
                                label="Download summary refinement prompt",
                                data=refinement_prompt,
                                file_name=f"{file_stem}.summary_refine_prompt.txt",
                                mime="text/plain",
                                key=f"download_summary_prompt_{file_stem}"
                            )
                            if st.button("Refine Thread Summary with Ollama"):
                                try:
                                    refined_summary = run_ollama_prompt(model, refinement_prompt)
                                    refined_summary_payload = {
                                        "content": refined_summary,
                                        "model": model,
                                        "mode": refinement_mode,
                                        "label": build_refinement_label(model, refinement_mode),
                                    }
                                    st.session_state[refined_summary_key] = refined_summary_payload
                                    st.success(refined_summary_payload["label"])
                                    st.rerun()
                                except requests.exceptions.RequestException as e:
                                    st.error(f"Failed to connect to Ollama: {e}. Make sure Ollama is running on localhost:11434.")
                            if refined_summary_payload and st.button("Clear Refined Summary"):
                                st.session_state.pop(refined_summary_key, None)
                                st.rerun()

                            if view_mode == "Documentation":
                                for i, message in enumerate(messages, 1):
                                    st.markdown(f"**[{i}] {ts_to_str(message['timestamp'])} {message['role']}:** {message['content']}")
                                    st.write("")
                            elif view_mode == "Hierarchical":
                                for i, message in enumerate(messages, 1):
                                    with st.expander(f"[{i}] {ts_to_str(message['timestamp'])} {message['role']}"):
                                        st.write(message['content'])

                            st.subheader("AI Actions with Ollama")
                            st.write("Use the same selected model for broader thread-level prompts after you review the summary.")

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