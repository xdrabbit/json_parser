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


if __name__ == "__main__":
    unittest.main()