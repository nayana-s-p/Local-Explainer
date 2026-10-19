# Validation — 6 October 2026

Target tested: Apple Silicon arm64, macOS 26.5.2, 16 GB unified memory. English was confirmed by the product owner. This is a development build; the SRS's release gates are not all passed.

## Evidence

- Python API/invariant suite: **14 tests passed**; project persistence, two-page PDF extraction, stable segment IDs, edits, malformed PDF/ZIP/manifest errors, per-segment invalidation, unsupported Hindi blocking, origin/host/session protections, path and ZIP traversal rejection, explicit overflow policy, overlap detection, and deletion confirmation.
- Real FFmpeg test: 320 × 180 H.264/AAC export at 24 FPS. Measured narration onset matches its 0.5 s placement within 100 ms. A later blocked export preserves the previous completed output.
- Cancellation test: a running worker is cancelled and its process exits; prior intermediate files remain.
- Restart test: a persisted running job is reconciled to interrupted by a fresh process.
- Integrity test: corrupting one WAV invalidates that segment and its dependent cues without erasing its neighbor.
- Storage/model test: low disk blocks setup, and a 0.6B configuration cannot be accepted as the required 1.7B model.
- Actual Blender validation test: a deliberately missing `MissingNeutralPose` mapping is named in the failure, and the job is not marked successful.
- UI smoke: project creation, editing two segments, reopening with saved text, setup screen, explicit frozen-frame preview past the end of the source video, and absence of page exceptions. Screenshots: projects.png, editor.png, setup.png.
- Real pipeline: a labeled imported macOS speech fixture → Rhubarb 1.14.0 → sample Sage Blender 5.2.2 rig → transparent PNG sequence → FFmpeg composition. Output metadata is recorded in integration-result.json, and sample-project/verified-sample.mp4 is retained.
- Frame recovery: deliberately corrupt/missing PNGs were regenerated; a valid neighboring frame retained its checksum.
- Accessibility: zero automated WCAG A/AA violations on project home and setup, plus visible keyboard focus.
- Packaged pipeline: the embedded server, bundled FFmpeg/FFprobe and Rhubarb, and external Blender completed the same sample through the HTTP API; see package-result.json.
- Native app: AppKit/WebKit wrapper starts its embedded localhost server and displays the editor. Final bundle includes the media tools, sample character, and documentation.

## Remaining release gates

- Gate A: explicit Qwen model download, actual English 1.7B speech generation, listening review, MPS stability, elapsed time, and peak memory. No model weights were downloaded in this build session. Do not claim this machine's 16 GB configuration is validated.
- Gate B: sample geometry/shape mapping is exercised. Independent artist rigs, fonts/textures, and alternate Blender versions remain untested.
- Gate C: the short landscape sample is verified. The specified 30–60 second and portrait acceptance exports still need review with real Qwen narration.
- Gate D: unit/worker cancellation and restart behavior are tested. Full-stage force termination/resume, scanned-page OCR confidence, low-disk render behavior, and OS-level offline/network capture require additional acceptance evidence.
- Gate E: the local app has an ad hoc signature. Clean-machine installation, notarization, public redistribution licensing/source obligations, and Windows/CUDA are not validated.

## Deliberate product limits

CustomVoice and VoiceDesign are supported adapter variants. Base voice cloning is optional in the SRS and is not exposed. Voice configuration applies to the project; segment regeneration and audio replacement are individual. Timing uses start-time fields and a synchronized timeline; draft blocks have no guessed audio duration. Overlay uses a fixed square alpha canvas and the prepared Blender camera. A completed export provides the authoritative composition preview; source preview uses the same timing/layout/mix with separate browser media elements. The source preview holds the last frame and continues narration when the explicit extension policy is selected; the exported MP4 uses the same duration. Portable archive export has an API endpoint; importing portable archives is not exposed yet. Local OCR is offered only when Tesseract is installed and requires review.
