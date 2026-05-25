#!/usr/bin/env bash
# macOS packaging — .dmg with hardened-runtime codesign + notarization
# (T148, research R-13 + R-35).
#
# Produces:
#   <OUT_DIR>/AgentTower-Control-Panel-<version>.dmg
# The DMG contains a hardened-runtime-signed, notarized + stapled .app
# bundle. Apple Gatekeeper will admit it without an internet round-trip
# at first launch.
#
# Prerequisites (operator side — this script is unverified by the bench;
# it MUST be run on macOS 13+ with Xcode 13+ installed):
#   - macOS 13 (Ventura)+ build host
#   - Flutter SDK on PATH (3.27 per FVM pin) with macOS desktop enabled
#   - Apple Developer ID Application certificate installed in login keychain
#     (reused from agenttowerd CA per R-35)
#   - create-dmg on PATH (`brew install create-dmg`)
#   - notarytool from Xcode 13+
#   - Stored notarization profile created via:
#       xcrun notarytool store-credentials <profile-name> \
#         --apple-id <appleid> --team-id <teamid> --password <app-specific-pw>
#
# Required environment variables:
#   DEVELOPER_ID_APP     full subject of the Developer ID Application cert
#                        (e.g. "Developer ID Application: Opensoft Inc (ABCDE12345)")
#   NOTARY_PROFILE       notarytool stored-credentials profile name
#
# Environment overrides:
#   FLUTTER              path/name of flutter executable (default: flutter)
#   OUT_DIR              destination dir (default: build/dist/macos)
#   APP_VERSION          override version (default: parsed from pubspec.yaml)
#   APP_BUNDLE_ID        override Bundle ID (default: parsed from
#                        macos/Runner/Configs/AppInfo.xcconfig — rebranded to
#                        "one.opensoft.agenttower.control_panel" per T178)
#   SKIP_NOTARIZATION    "1" to skip notarytool (dev builds only — produces an
#                        artifact that will be rejected by Gatekeeper)
#
# Exit status:
#   0 on success
#   non-zero with a single human-readable error line on any failure

set -euo pipefail

# ----- 1. Resolve paths --------------------------------------------------
TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${TOOLS_DIR}/.." && pwd)"

if [[ ! -f "${APP_DIR}/pubspec.yaml" ]]; then
  echo "ERROR: cannot locate pubspec.yaml relative to $0 (expected ${APP_DIR}/pubspec.yaml)" >&2
  exit 2
fi

FLUTTER="${FLUTTER:-flutter}"
if ! command -v "${FLUTTER}" >/dev/null 2>&1; then
  echo "ERROR: ${FLUTTER} not on PATH. Set FLUTTER=/path/to/flutter or install Flutter ≥ 3.27." >&2
  exit 2
fi

if ! command -v codesign >/dev/null 2>&1; then
  echo "ERROR: codesign not on PATH (Xcode command line tools required)." >&2
  exit 2
fi

if ! command -v create-dmg >/dev/null 2>&1; then
  echo "ERROR: create-dmg not on PATH (run 'brew install create-dmg')." >&2
  exit 2
fi

SKIP_NOTARIZATION="${SKIP_NOTARIZATION:-0}"
if [[ "${SKIP_NOTARIZATION}" != "1" ]] && ! xcrun --find notarytool >/dev/null 2>&1; then
  echo "ERROR: notarytool not available (Xcode 13+ required). Set SKIP_NOTARIZATION=1 for unnotarized dev builds." >&2
  exit 2
fi

# ----- 2. Resolve version + bundle id -----------------------------------
APP_VERSION="${APP_VERSION:-}"
if [[ -z "${APP_VERSION}" ]]; then
  APP_VERSION="$(awk '/^version:/ { sub(/\+.*/, "", $2); print $2; exit }' "${APP_DIR}/pubspec.yaml")"
fi
if [[ -z "${APP_VERSION}" ]]; then
  echo "ERROR: could not parse version from pubspec.yaml" >&2
  exit 2
fi

APP_BUNDLE_ID="${APP_BUNDLE_ID:-}"
if [[ -z "${APP_BUNDLE_ID}" ]]; then
  APP_BUNDLE_ID="$(awk -F'= ' '/PRODUCT_BUNDLE_IDENTIFIER/ { print $2; exit }' "${APP_DIR}/macos/Runner/Configs/AppInfo.xcconfig" 2>/dev/null || true)"
fi
if [[ -z "${APP_BUNDLE_ID}" ]]; then
  APP_BUNDLE_ID="one.opensoft.agenttower.control_panel"
  echo "WARN: APP_BUNDLE_ID not derivable — using fallback '${APP_BUNDLE_ID}'." >&2
fi

OUT_DIR="${OUT_DIR:-${APP_DIR}/build/dist/macos}"
mkdir -p "${OUT_DIR}"

# ----- 3. Validate required env vars (only when notarizing) -------------
if [[ "${SKIP_NOTARIZATION}" != "1" ]]; then
  : "${DEVELOPER_ID_APP:?ERROR: DEVELOPER_ID_APP env var is required (e.g. \"Developer ID Application: Opensoft Inc (ABCDE12345)\")}"
  : "${NOTARY_PROFILE:?ERROR: NOTARY_PROFILE env var is required (notarytool stored-credentials profile name)}"
fi

# ----- 4. flutter build --------------------------------------------------
echo "==> flutter build macos --release (version ${APP_VERSION})"
(cd "${APP_DIR}" && "${FLUTTER}" build macos --release)

APP_BUNDLE="${APP_DIR}/build/macos/Build/Products/Release/agenttower_control_panel.app"
if [[ ! -d "${APP_BUNDLE}" ]]; then
  # Flutter sometimes names the app from CFBundleName; fall back to a glob.
  APP_BUNDLE="$(find "${APP_DIR}/build/macos/Build/Products/Release" -maxdepth 1 -type d -name "*.app" | head -1)"
fi
if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "ERROR: no .app bundle found under ${APP_DIR}/build/macos/Build/Products/Release/" >&2
  exit 3
fi
echo "    .app bundle: ${APP_BUNDLE}"

# ----- 5. codesign (hardened runtime) -----------------------------------
if [[ "${SKIP_NOTARIZATION}" != "1" ]]; then
  echo "==> codesign --options runtime --timestamp"
  # Sign nested frameworks/helpers first, then the outer bundle.
  find "${APP_BUNDLE}" -type f \( -name "*.dylib" -o -name "*.framework" -o -perm +111 \) -print0 \
    | xargs -0 -I {} codesign --force --options runtime --timestamp \
        --sign "${DEVELOPER_ID_APP}" {} 2>/dev/null || true
  codesign --force --options runtime --timestamp \
    --sign "${DEVELOPER_ID_APP}" \
    --entitlements "${APP_DIR}/macos/Runner/Release.entitlements" \
    "${APP_BUNDLE}"

  echo "==> codesign --verify --deep --strict"
  codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}"
else
  echo "==> SKIP codesign (SKIP_NOTARIZATION=1 — dev build only)"
fi

# ----- 6. Build DMG -----------------------------------------------------
DMG_OUT="${OUT_DIR}/AgentTower-Control-Panel-${APP_VERSION}.dmg"
rm -f "${DMG_OUT}"
echo "==> create-dmg → ${DMG_OUT}"
create-dmg \
  --volname "AgentTower Control Panel ${APP_VERSION}" \
  --window-pos 200 120 \
  --window-size 600 400 \
  --icon-size 100 \
  --icon "$(basename "${APP_BUNDLE}")" 175 200 \
  --hide-extension "$(basename "${APP_BUNDLE}")" \
  --app-drop-link 425 200 \
  --no-internet-enable \
  "${DMG_OUT}" \
  "${APP_BUNDLE}"

if [[ "${SKIP_NOTARIZATION}" != "1" ]]; then
  # ----- 7. codesign the DMG itself --------------------------------------
  echo "==> codesign DMG"
  codesign --force --sign "${DEVELOPER_ID_APP}" --timestamp "${DMG_OUT}"

  # ----- 8. Notarize + staple --------------------------------------------
  echo "==> notarytool submit (profile: ${NOTARY_PROFILE})"
  xcrun notarytool submit "${DMG_OUT}" \
    --keychain-profile "${NOTARY_PROFILE}" \
    --wait

  echo "==> stapler staple"
  xcrun stapler staple "${DMG_OUT}"
  xcrun stapler validate "${DMG_OUT}"

  echo "==> spctl --assess (Gatekeeper acceptance check)"
  spctl --assess --type install --verbose "${DMG_OUT}" || {
    echo "ERROR: Gatekeeper rejected the signed+notarized DMG. See spctl output above." >&2
    exit 4
  }
else
  echo "==> SKIP notarization + staple (SKIP_NOTARIZATION=1)"
fi

# ----- 9. Report --------------------------------------------------------
echo ""
echo "=== macOS packaging complete ==="
echo "  DMG     : ${DMG_OUT}"
echo "  Version : ${APP_VERSION}"
echo "  Bundle  : ${APP_BUNDLE_ID}"
if [[ "${SKIP_NOTARIZATION}" == "1" ]]; then
  echo "  Status  : UNSIGNED dev build (will be rejected by Gatekeeper)"
else
  echo "  Status  : Signed + notarized + stapled"
fi
echo ""
