import unittest
import io
import json
import zipfile

import streamlit_viewer as viewer


def build_sample_conversation():
    return {
        "title": "closed - Legal strategy steps",
        "create_time": 1700000000,
        "update_time": 1700000300,
        "mapping": {
            "root": {"message": None},
            "m2": {
                "message": {
                    "create_time": 1700000200,
                    "author": {"role": "assistant"},
                    "content": {
                        "parts": [
                            "Here is a screenshot ![Uploaded image](https://chatgpt.com/backend-api/estuary/content?id=file_ABC123&sig=xyz) and analysis."
                        ]
                    },
                }
            },
            "m1": {
                "message": {
                    "create_time": 1700000100,
                    "author": {"role": "user"},
                    "content": {
                        "parts": [
                            "I found the notice.",
                            {
                                "content_type": "image_asset_pointer",
                                "asset_pointer": "sediment://file_DEF456",
                                "filename": "notice.png",
                            },
                        ]
                    },
                }
            },
        },
    }


def build_mixed_conversation():
    return {
        "title": "mixed notes",
        "create_time": 1700001000,
        "update_time": 1700001400,
        "mapping": {
            "root": {"message": None},
            "m1": {
                "message": {
                    "create_time": 1700001100,
                    "author": {"role": "user"},
                    "content": {"parts": ["I need help debugging a Streamlit layout issue in my app."]},
                }
            },
            "m2": {
                "message": {
                    "create_time": 1700001200,
                    "author": {"role": "user"},
                    "content": {"parts": ["The court order required a response by January 5, 2025 and I have the screenshot proof."]},
                }
            },
            "m3": {
                "message": {
                    "create_time": 1700001300,
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Focus the filing on the missed compliance deadline and attach the evidence."]},
                }
            },
        },
    }


def build_non_legal_conversation():
    return {
        "title": "software notes",
        "create_time": 1700002000,
        "update_time": 1700002300,
        "mapping": {
            "root": {"message": None},
            "m1": {
                "message": {
                    "create_time": 1700002100,
                    "author": {"role": "user"},
                    "content": {"parts": ["I need help debugging Python code in a Streamlit app and reviewing a pull request."]},
                }
            },
            "m2": {
                "message": {
                    "create_time": 1700002200,
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Try refactoring the JSON parser and checking git diff output."]},
                }
            },
        },
    }


def build_uncertain_conversation():
    return {
        "title": "case context spillover",
        "create_time": 1700003000,
        "update_time": 1700003400,
        "mapping": {
            "root": {"message": None},
            "m1": {
                "message": {
                    "create_time": 1700003100,
                    "author": {"role": "user"},
                    "content": {"parts": ["The court order required the response by January 5, 2025."]},
                }
            },
            "m2": {
                "message": {
                    "create_time": 1700003200,
                    "author": {"role": "user"},
                    "content": {"parts": ["I am overwhelmed and trying to plan around everything next week."]},
                }
            },
            "m3": {
                "message": {
                    "create_time": 1700003300,
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Attach the screenshot evidence and focus on the missed compliance deadline."]},
                }
            },
        },
    }


def build_contradiction_conversation():
    return {
        "title": "contradiction thread",
        "create_time": 1700004000,
        "update_time": 1700004400,
        "mapping": {
            "root": {"message": None},
            "m1": {
                "message": {
                    "create_time": 1700004100,
                    "author": {"role": "user"},
                    "content": {"parts": ["The court order required a response by January 5, 2025."]},
                }
            },
            "m2": {
                "message": {
                    "create_time": 1700004200,
                    "author": {"role": "user"},
                    "content": {"parts": ["They failed to comply and then gave a different story about why the document was never provided."]},
                }
            },
            "m3": {
                "message": {
                    "create_time": 1700004300,
                    "author": {"role": "assistant"},
                    "content": {"parts": ["That inconsistency supports a contradiction pattern tied to noncompliance."]},
                }
            },
        },
    }


def build_claims_issues_conversation():
    return {
        "title": "claims thread",
        "create_time": 1700005000,
        "update_time": 1700005400,
        "mapping": {
            "root": {"message": None},
            "m1": {
                "message": {
                    "create_time": 1700005100,
                    "author": {"role": "user"},
                    "content": {"parts": ["My claim is that the missed deadline violated the court order."]},
                }
            },
            "m2": {
                "message": {
                    "create_time": 1700005200,
                    "author": {"role": "assistant"},
                    "content": {"parts": ["The central issue is noncompliance, and the remedy may be a motion to enforce."]},
                }
            },
            "m3": {
                "message": {
                    "create_time": 1700005300,
                    "author": {"role": "assistant"},
                    "content": {"parts": ["Whether the judge will grant relief remains an open question."]},
                }
            },
        },
    }


class StreamlitViewerTests(unittest.TestCase):
    def test_extract_content_text_rewrites_image_links_and_attachments(self):
        content = {
            "parts": [
                "See this ![Uploaded image](https://chatgpt.com/backend-api/estuary/content?id=file_ABC123&sig=xyz)",
                {
                    "content_type": "image_asset_pointer",
                    "asset_pointer": "sediment://file_DEF456",
                    "filename": "notice.png",
                },
            ]
        }

        text, attachments, evidence_refs = viewer.extract_content_text(content)

        self.assertIn("[Referenced image: Uploaded image]", text)
        self.assertIn("[Attachment: image - notice.png]", text)
        self.assertEqual(attachments, ["[Referenced image: Uploaded image]", "[Attachment: image - notice.png]"])
        self.assertEqual([record["asset_id"] for record in evidence_refs], ["file_ABC123", "file_DEF456"])

    def test_extract_messages_from_conversation_sorts_and_cleans(self):
        conversation = build_sample_conversation()

        messages = viewer.extract_messages_from_conversation(conversation)

        self.assertEqual([message["role"] for message in messages], ["USER", "ASSISTANT"])
        self.assertIn("[Attachment: image - notice.png]", messages[0]["content"])
        self.assertIn("[Referenced image: Uploaded image]", messages[1]["content"])

    def test_build_evidence_manifest_assigns_exhibits(self):
        conversation = build_sample_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)

        manifest = viewer.build_evidence_manifest(conversation, messages)

        self.assertEqual(manifest["evidence_count"], 2)
        self.assertEqual([exhibit["exhibit_id"] for exhibit in manifest["exhibits"]], ["EXH-001", "EXH-002"])
        self.assertEqual(manifest["exhibits"][0]["asset_id"], "file_DEF456")
        self.assertEqual(manifest["exhibits"][1]["asset_id"], "file_ABC123")

    def test_build_project_memory_markdown_includes_layers_and_evidence(self):
        conversation = build_sample_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        manifest = viewer.build_evidence_manifest(conversation, messages)

        memory_markdown = viewer.build_project_memory_markdown(conversation, messages, manifest)

        self.assertIn("## Layered Retrieval Strategy", memory_markdown)
        self.assertIn("## Evidence Layer", memory_markdown)
        self.assertIn("EXH-001", memory_markdown)
        self.assertIn("asset_id=file_DEF456", memory_markdown)

    def test_build_thread_export_keeps_evidence_refs(self):
        conversation = build_sample_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)

        exported = viewer.build_thread_export(conversation, messages)

        self.assertEqual(exported["message_count"], 2)
        self.assertIn("evidence_refs", exported["messages"][0])
        self.assertEqual(exported["messages"][0]["evidence_refs"][0]["asset_id"], "file_DEF456")

    def test_build_thread_summary_markdown_produces_top_layer_handoff(self):
        conversation = build_sample_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        manifest = viewer.build_evidence_manifest(conversation, messages)

        summary_markdown = viewer.build_thread_summary_markdown(conversation, messages, manifest)

        self.assertIn("# Thread Summary: closed - Legal strategy steps", summary_markdown)
        self.assertIn("## Executive Summary", summary_markdown)
        self.assertIn("## Retrieval Handoff", summary_markdown)
        self.assertIn("Evidence references: 2", summary_markdown)
        self.assertIn("Use this summary as the top layer", summary_markdown)

    def test_build_summary_refinement_prompt_includes_mode_and_source_summary(self):
        conversation = build_sample_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        manifest = viewer.build_evidence_manifest(conversation, messages)
        summary_markdown = viewer.build_thread_summary_markdown(conversation, messages, manifest)

        prompt = viewer.build_summary_refinement_prompt(summary_markdown, "Executive Brief")

        self.assertIn("Task:", prompt)
        self.assertIn("compact executive brief", prompt)
        self.assertIn("Source summary:", prompt)
        self.assertIn("# Thread Summary: closed - Legal strategy steps", prompt)

    def test_refinement_helpers_build_stable_labels(self):
        key = viewer.refinement_session_key("closed_Legal_strategy_steps")
        label = viewer.build_refinement_label("mistral-nemo:latest", "Executive Brief")

        self.assertEqual(key, "refined_summary::closed_Legal_strategy_steps")
        self.assertIn("mistral-nemo:latest", label)
        self.assertIn("Executive Brief", label)

    def test_build_batch_summary_zip_contains_summary_and_manifest(self):
        conversation = build_sample_conversation()

        archive_bytes = viewer.build_batch_summary_zip([conversation])

        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            names = archive.namelist()
            self.assertIn("summaries/closed_-_Legal_strategy_steps.summary.md", names)
            self.assertIn("summaries/manifest.json", names)

            summary_text = archive.read("summaries/closed_-_Legal_strategy_steps.summary.md").decode("utf-8")
            manifest = json.loads(archive.read("summaries/manifest.json").decode("utf-8"))

        self.assertIn("# Thread Summary: closed - Legal strategy steps", summary_text)
        self.assertEqual(manifest["conversation_count"], 1)
        self.assertEqual(manifest["summaries"][0]["title"], "closed - Legal strategy steps")

    def test_general_audience_filter_redacts_intimate_terms(self):
        source = "A romantic and intimate exchange included explicit details."

        filtered = viewer.apply_content_filter(source, "General Audience")

        self.assertNotIn("romantic", filtered.lower())
        self.assertNotIn("exchange included explicit details", filtered.lower())
        self.assertIn("[redacted intimate detail]", filtered)

    def test_build_batch_summary_zip_records_filter_mode(self):
        conversation = build_sample_conversation()

        archive_bytes = viewer.build_batch_summary_zip([conversation], filter_mode="General Audience")

        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            manifest = json.loads(archive.read("summaries/manifest.json").decode("utf-8"))

        self.assertEqual(manifest["summaries"][0]["filter_mode"], "General Audience")

    def test_build_legal_relevance_manifest_detects_mixed_thread(self):
        conversation = build_mixed_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)

        manifest = viewer.build_legal_relevance_manifest(conversation, messages)

        self.assertEqual(manifest["thread_classification"], "uncertain")
        self.assertTrue(manifest["mixed_domain"])
        self.assertGreaterEqual(manifest["included_message_count"], 2)

    def test_build_legal_memory_markdown_has_traceable_sections(self):
        conversation = build_mixed_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        evidence_manifest = viewer.build_evidence_manifest(conversation, messages)
        relevance_manifest = viewer.build_legal_relevance_manifest(conversation, messages)

        legal_memory = viewer.build_legal_memory_markdown(conversation, messages, evidence_manifest, relevance_manifest)

        self.assertIn("# Legal Memory Artifact: mixed notes", legal_memory)
        self.assertIn("## Matter Summary", legal_memory)
        self.assertIn("## Governing Orders / Duties", legal_memory)
        self.assertIn("## Source Scope / Notes", legal_memory)
        self.assertIn("[msg 2]", legal_memory)

    def test_build_legal_timeline_json_includes_traceable_events(self):
        conversation = build_mixed_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        evidence_manifest = viewer.build_evidence_manifest(conversation, messages)
        relevance_manifest = viewer.build_legal_relevance_manifest(conversation, messages)

        timeline = viewer.build_legal_timeline_json(conversation, messages, evidence_manifest, relevance_manifest)

        self.assertEqual(timeline["conversation_title"], "mixed notes")
        self.assertGreaterEqual(timeline["event_count"], 2)
        self.assertEqual(timeline["events"][0]["message_index"], 2)
        self.assertIn(timeline["events"][0]["event_type"], {"dated_event", "obligation_or_dispute"})

    def test_build_contradiction_index_json_detects_signals(self):
        conversation = build_contradiction_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        evidence_manifest = viewer.build_evidence_manifest(conversation, messages)
        relevance_manifest = viewer.build_legal_relevance_manifest(conversation, messages)

        contradictions = viewer.build_contradiction_index_json(conversation, messages, evidence_manifest, relevance_manifest)

        self.assertGreaterEqual(contradictions["contradiction_count"], 1)
        self.assertIn("noncompliance", contradictions["items"][0]["signals"])

    def test_build_claims_issues_json_detects_categories(self):
        conversation = build_claims_issues_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        evidence_manifest = viewer.build_evidence_manifest(conversation, messages)
        relevance_manifest = viewer.build_legal_relevance_manifest(conversation, messages)

        claims_issues = viewer.build_claims_issues_json(conversation, messages, evidence_manifest, relevance_manifest)

        self.assertGreaterEqual(claims_issues["entry_count"], 3)
        all_categories = {category for entry in claims_issues["entries"] for category in entry["categories"]}
        self.assertIn("claim", all_categories)
        self.assertIn("issue", all_categories)
        self.assertIn("remedy", all_categories)

    def test_build_batch_legal_memory_zip_exports_artifacts_for_legal_threads(self):
        conversation = build_mixed_conversation()

        archive_bytes = viewer.build_batch_legal_memory_zip([conversation])

        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read("legal_memory/manifest.json").decode("utf-8"))

        self.assertIn("legal_relevance/mixed_notes.legal_relevance.json", names)
        self.assertIn("legal_timeline/mixed_notes.timeline.json", names)
        self.assertIn("legal_contradictions/mixed_notes.contradictions.json", names)
        self.assertIn("legal_claims_issues/mixed_notes.claims_issues.json", names)
        self.assertIn("legal_memory/mixed_notes.legal_memory.md", names)
        self.assertEqual(manifest["threads"][0]["export_status"], "exported")

    def test_build_batch_legal_memory_zip_skips_non_legal_memory_export(self):
        conversation = build_non_legal_conversation()

        archive_bytes = viewer.build_batch_legal_memory_zip([conversation])

        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as archive:
            names = archive.namelist()
            manifest = json.loads(archive.read("legal_memory/manifest.json").decode("utf-8"))

        self.assertIn("legal_relevance/software_notes.legal_relevance.json", names)
        self.assertNotIn("legal_memory/software_notes.legal_memory.md", names)
        self.assertEqual(manifest["threads"][0]["export_status"], "skipped_non_legal")

    def test_uncertain_material_is_demoted_to_source_scope_notes(self):
        conversation = build_uncertain_conversation()
        messages = viewer.extract_messages_from_conversation(conversation)
        evidence_manifest = viewer.build_evidence_manifest(conversation, messages)
        relevance_manifest = viewer.build_legal_relevance_manifest(conversation, messages)

        legal_memory = viewer.build_legal_memory_markdown(conversation, messages, evidence_manifest, relevance_manifest)

        self.assertIn("## Source Scope / Notes", legal_memory)
        self.assertIn("Possible contextual relevance only", legal_memory)
        self.assertIn("overwhelmed and trying to plan", legal_memory)


if __name__ == "__main__":
    unittest.main()