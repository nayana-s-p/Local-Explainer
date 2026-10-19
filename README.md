# Local Explainer for Mac

A local macOS app based on the supplied Video Explainer SRS and Agent Build Guide. The native AppKit/WebKit window launches an embedded Python localhost service and serves a React/TypeScript editor. Projects, media, SQLite state, and generated files remain on your Mac.

## Open the app

Double-click `dist/Local Explainer.app`. The build embeds Python, the editor, FFmpeg/FFprobe, and Rhubarb. Blender is installed separately in `/Applications/Blender.app`. The Rhubarb upstream macOS binary is x86_64 and needs Rosetta; it has been exercised on this Mac.

1. Create a project or choose **Try the sample project**.
2. Import a PDF and video. Extract and review the script, or write narration directly.
3. Edit/split/merge segments and set each start time in seconds. Draft timeline blocks have no duration estimate.
4. Open **Setup & capabilities**, then explicitly download the Qwen3-TTS 1.7B model/runtime, or provide existing local paths. English is the default. Select MPS or explicit CPU diagnostic mode.
5. Generate and preview individual narration segments. You can also replace a segment with a PCM WAV. Replacement provenance is retained.
6. Import a prepared Blender ZIP with a manifest, validate it, generate mouth cues, and render the character.
7. Set overlay placement, visibility, and audio mix. Export MP4 and open its local output folder.

If narration exceeds the video, explicitly select **Extend with a frozen last frame** or move the segments. Speech is never trimmed automatically. Export refuses overlapping speech, missing/stale narration, and missing/stale enabled character frames.

## Storage and recovery

Application data lives in `~/Library/Application Support/Local Explainer/`. SQLite indexes projects/jobs, and each project contains original copies, audio, cues, alpha frames, and versioned outputs. Previous completed exports survive subsequent failed jobs. Edits invalidate dependent artifacts; unrelated audio/cues remain reusable. Retrying a segment job skips valid completed segments. Character rendering resumes missing frames for matching input fingerprints. Interrupted jobs are reconciled on restart.

The service binds to `127.0.0.1`, uses a per-launch session secret, checks Host/Origin, and requires a custom header for writes. Paths and ZIP entries stay within managed roots. Model inference forces offline Hugging Face/Transformers operation. Only an explicit model Setup job accesses model/package download services. Raw third-party worker output uses anonymous temporary files and is not included in diagnostics.

## Development

Use Python 3.12 and Node. No model weights belong in the repository.

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.lock
cd frontend
npm ci
npm run build
cd ..
EXPLAINER_TOKEN=development .venv/bin/python server.py
```

Open `http://127.0.0.1:8765/?token=development` once to establish a session. Rebuild the frontend during development; the backend serves the built assets under the same local origin. For end-to-end UI testing, use the built assets served by the backend.

```sh
.venv/bin/python -m pytest -q
cd frontend && node ui-smoke.mjs
cd ..
blender --background --python sample-character/create_character.py
.venv/bin/python scripts/integration.py
scripts/build-mac.sh
```

The UI smoke script expects a test server with `EXPLAINER_TOKEN=development`, and uses Playwright Chromium. `npx playwright install chromium` installs that test browser. Integration uses a clearly labeled imported macOS speech fixture so the real Rhubarb → Blender → FFmpeg pipeline can be checked before downloading Qwen.

## Validation status

See [docs/VALIDATION.md](docs/VALIDATION.md). This is a working development build, not a declaration that every SRS release gate passed. Qwen model weights have not been downloaded, and English 1.7B inference on this 16 GB MPS machine still needs validation. The specification's Apple Silicon planning target is 24 GB or more.

See [docs/CHARACTER_BUNDLES.md](docs/CHARACTER_BUNDLES.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) before preparing a custom character or distributing the app.
