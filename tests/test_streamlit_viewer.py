import unittest

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


if __name__ == "__main__":
    unittest.main()