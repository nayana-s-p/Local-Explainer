# Third-party software — development build

This build orchestrates these projects. The source, license, and build configuration must be retained/reviewed before public distribution. This is a local development package with an ad hoc signature, not a notarized release.

| Component | Source | License / distribution note |
|---|---|---|
| Python 3.12 | https://www.python.org/ | PSF License; embedded by PyInstaller |
| PyInstaller | https://pyinstaller.org/ | GPL with bootloader exception |
| React | https://github.com/facebook/react | MIT |
| Vite | https://github.com/vitejs/vite | MIT; build tool |
| Lucide | https://github.com/lucide-icons/lucide | ISC |
| FastAPI | https://github.com/fastapi/fastapi | MIT |
| Starlette | https://github.com/Kludex/starlette | BSD-3-Clause |
| Uvicorn | https://github.com/Kludex/uvicorn | BSD-3-Clause |
| Pydantic | https://github.com/pydantic/pydantic | MIT |
| PyMuPDF / MuPDF | https://pymupdf.readthedocs.io/ | AGPL-3.0 or commercial license; obtain appropriate licensing before distributing a closed-source product |
| imageio-ffmpeg | https://github.com/imageio/imageio-ffmpeg | BSD-2-Clause for the wrapper; bundled FFmpeg has separate terms |
| FFmpeg / FFprobe | https://ffmpeg.org/ | LGPL/GPL depending on exact encoder/build flags. The included H.264-capable binaries must be reviewed with their build flags and corresponding source before public distribution |
| Rhubarb Lip Sync 1.14.0 | https://github.com/DanielSWolf/rhubarb-lip-sync | MIT and third-party permissive notices, bundled in tools/rhubarb/LICENSE.md; macOS binary is x86_64 and uses Rosetta on Apple Silicon |
| Blender 5.2.2 | https://www.blender.org/ | GPL; externally installed, not embedded |
| Qwen3-TTS | https://github.com/QwenLM/Qwen3-TTS | Apache-2.0; runtime/model install is explicit in Setup; weights are not included |
| PyTorch | https://pytorch.org/ | BSD-style; isolated optional speech runtime |
| Tesseract | https://github.com/tesseract-ocr/tesseract | Apache-2.0; optional local OCR |

Python dependencies are recorded in requirements.lock. UI dependencies and transitive versions are recorded in frontend/package-lock.json. The optional Qwen runtime is installed separately; qwen-tts is pinned to 0.1.1. Its transitive versions must be captured after a successful hardware validation.

The sample Sage character is generated from original procedural geometry in sample-character/create_character.py. The sample fixture WAV uses macOS system speech for integration testing and is clearly labeled in the app. It is not Qwen output or an automatic fallback provider.
