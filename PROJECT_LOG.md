# Project Log

## 2026-03-23

### Summary
- Confirmed this repo is a Streamlit-based viewer/parser for ChatGPT `conversations.json` exports.
- Added conversation-level exports for raw JSON, flattened thread JSON, clean transcript Markdown, evidence manifest JSON, and legal project memory Markdown.
- Added attachment/image reference extraction so evidence can be represented as a layered retrieval system instead of raw payload blobs.
- Added a small regression suite and refactored the app so the core logic can be imported and tested without launching the Streamlit UI.
- Switched the git remote to GitHub and pushed the current checkpoint.

### Current App State
- Main app: `streamlit_viewer.py`
- Launchers: `launch_streamlit.sh`, `launch.bat`, `launch_jsonParser.bat`
- Tests: `tests/test_streamlit_viewer.py`
- Latest pushed commit when this log was created: `56a2bb4`
- GitHub remote: `git@github.com:xdrabbit/json_parser.git`

### Export Layers Now Available
1. Raw conversation JSON
2. Thread messages JSON
3. Evidence manifest JSON
4. Clean transcript Markdown
5. Legal project memory Markdown

### Rationale
- Raw export objects are useful for archival fidelity but too noisy for direct project-memory use.
- Clean transcript and legal memory exports are better top-layer sources for ChatGPT Projects.
- Evidence references should stay in a lower layer and point down to the original files only when needed.

### Testing Added
- Regression coverage currently checks:
  - image/link evidence extraction
  - message extraction and sort order
  - evidence manifest generation
  - project memory generation
  - thread export preservation of evidence references

### Recommended Next Steps
1. Pull this repo on `blackbird` and continue development there.
2. Recreate the Python environment and run the regression suite.
3. Start the next phase on the stronger machine:
   - OCR for referenced images/files
   - attachment resolution against full ChatGPT export folders
   - richer evidence manifests
   - optional MCP server for hierarchical retrieval

### Suggested `blackbird` Bootstrap
```bash
git clone git@github.com:xdrabbit/json_parser.git
cd json_parser
python3 -m venv venv
source venv/bin/activate
pip install streamlit requests
python -m unittest discover -s tests -v
bash launch_streamlit.sh
```

### Notes
- `PROJECT_LOG.md` exists so key progress and decisions are stored in the repo instead of only in the chat client.
- If this becomes the standard handoff mechanism, append new dated entries rather than rewriting older ones.

### Next Session Handoff
1. Work from `blackbird`, not the older Mac Mini.
2. Start by confirming the pulled commit and running the regression suite.
3. Re-launch the Streamlit app only after tests pass.
4. Next engineering target: enrich the evidence layer rather than broadening the UI.
5. Priority order for the next phase:
  - ingest full ChatGPT export folders, not just `conversations.json`
  - resolve attachment/image files from export references
  - add OCR/text extraction for evidence assets
  - upgrade evidence manifest entries with OCR text, summaries, and relevance notes
  - only after the data model is solid, consider an MCP server for hierarchical retrieval
6. Keep `PROJECT_LOG.md` updated as the durable handoff record between machines/sessions.