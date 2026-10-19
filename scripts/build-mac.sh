#!/bin/zsh
set -euo pipefail
cd "${0:A:h:h}"
(cd frontend && npm run build)
.venv/bin/pyinstaller --noconfirm --clean --name ExplainerServer --onedir \
 --add-data 'frontend/dist:frontend/dist' --add-data 'workers:workers' --add-data 'sample-project:sample-project' \
 --add-binary '/opt/homebrew/bin/ffprobe:.' --collect-all imageio_ffmpeg --collect-all pymupdf \
 --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
 --hidden-import uvicorn.protocols.http.h11_impl --hidden-import uvicorn.protocols.websockets.auto \
 server.py > build-server.log 2>&1
APP='dist/Local Explainer.app'
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
rm -rf "$APP/Contents/Resources/server"
cp -R dist/ExplainerServer "$APP/Contents/Resources/server"
if [[ -d tools/Rhubarb-Lip-Sync-1.14.0-macOS ]]; then
 mkdir -p "$APP/Contents/Resources/tools"
 mkdir -p "$APP/Contents/Resources/tools/rhubarb"
 cp tools/Rhubarb-Lip-Sync-1.14.0-macOS/{rhubarb,LICENSE.md,README.adoc} "$APP/Contents/Resources/tools/rhubarb/"
 cp -R tools/Rhubarb-Lip-Sync-1.14.0-macOS/res "$APP/Contents/Resources/tools/rhubarb/"
fi
swiftc native/Main.swift -O -o "$APP/Contents/MacOS/LocalExplainer" -framework AppKit -framework WebKit
cp -R docs "$APP/Contents/Resources/documentation"
cp THIRD_PARTY_NOTICES.md "$APP/Contents/Resources/"
cp native/Info.plist "$APP/Contents/Info.plist"
if [[ -f native/AppIcon.icns ]]; then cp native/AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"; fi
codesign --force --deep --sign - "$APP" > build-sign.log 2>&1
printf 'Built: %s\n' "$PWD/$APP"
