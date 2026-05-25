#!/usr/bin/env bash
# Linux packaging — AppImage primary + .deb secondary
# (T148, research R-13 + R-35).
#
# Produces:
#   <OUT_DIR>/AgentTower-Control-Panel-<version>-x86_64.AppImage
#   <OUT_DIR>/agenttower-control-panel_<version>_amd64.deb
# When GPG_SIGN_KEY is set, also produces .asc detached signatures next to
# each artifact (R-13 signing requirement).
#
# Prerequisites (operator side):
#   - Ubuntu 22.04+ build host (glibc 2.35+)
#   - Flutter SDK on PATH (3.27 per FVM pin; bench may pin elsewhere — honors
#     the FLUTTER env-var override the same way tools/bench_verify.sh does)
#   - flutter config --enable-linux-desktop already run once
#   - appimagetool on PATH (https://github.com/AppImage/AppImageKit/releases)
#   - dpkg-deb on PATH (preinstalled on Debian/Ubuntu)
#   - gpg on PATH (only if GPG_SIGN_KEY is set)
#
# Environment overrides:
#   FLUTTER              path/name of flutter executable (default: flutter)
#   OUT_DIR              destination dir (default: build/dist/linux)
#   APP_VERSION          override version (default: parsed from pubspec.yaml)
#   APP_ICON             absolute path to 256x256 PNG icon (default: built-in
#                        placeholder + warning — operator must supply real
#                        branding before public release; the Phase 1 T007
#                        assets/icons/ entry intentionally ships only severity
#                        icons, not an app launcher icon)
#   GPG_SIGN_KEY         GPG key id (email or fingerprint); if unset, artifacts
#                        ship unsigned + a non-fatal warning is printed
#   DEB_MAINTAINER       Maintainer field (default: "Opensoft <release@opensoft.one>")
#   APPLICATION_ID       reverse-DNS app id (default: parsed from
#                        linux/CMakeLists.txt — rebranded to
#                        "one.opensoft.agenttower.control_panel" per T178)
#   BUNDLE_DIR           pre-built bundle dir (default: build/linux/x64/release/bundle).
#                        When set, skips `flutter build` and packages the
#                        provided bundle directly — useful for CI where build
#                        and package run as separate stages.
#
# Exit status:
#   0 on success
#   non-zero with a single human-readable error line on any failure
#
# Smoke-test status (2026-05-25): bench has dpkg-deb 1.22.6 + gpg 2.4.4 +
# flutter 3.44.0; appimagetool is NOT installed in the bench, so AppImage
# packaging is operator-verified only. The dpkg-deb path is bench-runnable
# once a Linux release build exists.

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

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "ERROR: dpkg-deb not on PATH (required for .deb step)." >&2
  exit 2
fi

# appimagetool is optional in the sense that we still ship the .deb if it's
# missing — but we report it loudly so the operator notices.
APPIMAGETOOL_OK=1
if ! command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL_OK=0
  echo "WARN: appimagetool not on PATH — AppImage step will be skipped." >&2
  echo "      Install from https://github.com/AppImage/AppImageKit/releases" >&2
fi

# ----- 2. Resolve version + app id --------------------------------------
APP_VERSION="${APP_VERSION:-}"
if [[ -z "${APP_VERSION}" ]]; then
  # pubspec format: "version: 0.1.0+1" — strip the "+build" suffix for .deb / AppImage filenames.
  APP_VERSION="$(awk '/^version:/ { sub(/\+.*/, "", $2); print $2; exit }' "${APP_DIR}/pubspec.yaml")"
fi
if [[ -z "${APP_VERSION}" ]]; then
  echo "ERROR: could not parse version from pubspec.yaml" >&2
  exit 2
fi

APPLICATION_ID="${APPLICATION_ID:-}"
if [[ -z "${APPLICATION_ID}" ]]; then
  APPLICATION_ID="$(awk -F'"' '/set\(APPLICATION_ID/ { print $2; exit }' "${APP_DIR}/linux/CMakeLists.txt" 2>/dev/null || true)"
fi
if [[ -z "${APPLICATION_ID}" ]]; then
  APPLICATION_ID="one.opensoft.agenttower.control_panel"
  echo "WARN: APPLICATION_ID not found in linux/CMakeLists.txt — using fallback '${APPLICATION_ID}'." >&2
fi

BINARY_NAME="$(awk -F'"' '/set\(BINARY_NAME/ { print $2; exit }' "${APP_DIR}/linux/CMakeLists.txt" 2>/dev/null || echo agenttower_control_panel)"
DEB_MAINTAINER="${DEB_MAINTAINER:-Opensoft <release@opensoft.one>}"

OUT_DIR="${OUT_DIR:-${APP_DIR}/build/dist/linux}"
mkdir -p "${OUT_DIR}"

# ----- 3. flutter build (or use pre-built BUNDLE_DIR) -------------------
if [[ -n "${BUNDLE_DIR:-}" ]]; then
  BUILD_BUNDLE="${BUNDLE_DIR}"
  echo "==> SKIP flutter build (using BUNDLE_DIR=${BUILD_BUNDLE})"
else
  echo "==> flutter build linux --release (version ${APP_VERSION})"
  (cd "${APP_DIR}" && "${FLUTTER}" build linux --release)
  BUILD_BUNDLE="${APP_DIR}/build/linux/x64/release/bundle"
fi

if [[ ! -d "${BUILD_BUNDLE}" ]]; then
  echo "ERROR: expected Flutter bundle at ${BUILD_BUNDLE} not present." >&2
  exit 3
fi

# ----- 4. Stage AppDir ---------------------------------------------------
APPDIR="$(mktemp -d -t agenttower-control-panel-appdir-XXXXXX)"
trap 'rm -rf "${APPDIR}"' EXIT

mkdir -p "${APPDIR}/usr/bin" "${APPDIR}/usr/lib" "${APPDIR}/usr/share/applications" "${APPDIR}/usr/share/icons/hicolor/256x256/apps"

cp -r "${BUILD_BUNDLE}/." "${APPDIR}/usr/lib/${BINARY_NAME}/"
ln -s "../lib/${BINARY_NAME}/${BINARY_NAME}" "${APPDIR}/usr/bin/${BINARY_NAME}"

ICON_DEST="${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APPLICATION_ID}.png"
if [[ -n "${APP_ICON:-}" && -f "${APP_ICON}" ]]; then
  cp "${APP_ICON}" "${ICON_DEST}"
else
  # 1x1 transparent PNG placeholder — base64-decoded inline so the script
  # doesn't depend on a checked-in binary asset. Operator MUST supply a real
  # icon via APP_ICON for any public release.
  echo "WARN: APP_ICON not set or missing — embedding placeholder icon. Supply APP_ICON=/path/to/icon.png for releases." >&2
  printf 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkAAIAAAoAAv/lxKUAAAAASUVORK5CYII=' | base64 -d > "${ICON_DEST}"
fi

cat > "${APPDIR}/usr/share/applications/${APPLICATION_ID}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AgentTower Control Panel
Comment=Local-first operator UI for agenttowerd
Exec=${BINARY_NAME}
Icon=${APPLICATION_ID}
Categories=Development;
StartupWMClass=${BINARY_NAME}
Terminal=false
EOF

# AppImage requires the .desktop + icon at AppDir root (symlinked from the
# canonical XDG locations under usr/share).
ln -s "usr/share/applications/${APPLICATION_ID}.desktop" "${APPDIR}/${APPLICATION_ID}.desktop"
ln -s "usr/share/icons/hicolor/256x256/apps/${APPLICATION_ID}.png" "${APPDIR}/${APPLICATION_ID}.png"

cat > "${APPDIR}/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "${HERE}/usr/bin/agenttower_control_panel" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

# ----- 5. AppImage -------------------------------------------------------
APPIMAGE_OUT="${OUT_DIR}/AgentTower-Control-Panel-${APP_VERSION}-x86_64.AppImage"
if [[ "${APPIMAGETOOL_OK}" == "1" ]]; then
  echo "==> appimagetool → ${APPIMAGE_OUT}"
  ARCH=x86_64 appimagetool "${APPDIR}" "${APPIMAGE_OUT}"
else
  echo "==> SKIP AppImage (appimagetool unavailable)"
fi

# ----- 6. .deb -----------------------------------------------------------
DEB_STAGING="$(mktemp -d -t agenttower-control-panel-deb-XXXXXX)"
trap 'rm -rf "${APPDIR}" "${DEB_STAGING}"' EXIT

mkdir -p "${DEB_STAGING}/DEBIAN" "${DEB_STAGING}/opt/${BINARY_NAME}" "${DEB_STAGING}/usr/bin" "${DEB_STAGING}/usr/share/applications" "${DEB_STAGING}/usr/share/icons/hicolor/256x256/apps"

cp -r "${BUILD_BUNDLE}/." "${DEB_STAGING}/opt/${BINARY_NAME}/"
ln -sf "/opt/${BINARY_NAME}/${BINARY_NAME}" "${DEB_STAGING}/usr/bin/${BINARY_NAME}"

cp "${APPDIR}/usr/share/applications/${APPLICATION_ID}.desktop" "${DEB_STAGING}/usr/share/applications/"
cp "${ICON_DEST}" "${DEB_STAGING}/usr/share/icons/hicolor/256x256/apps/"

INSTALLED_SIZE_KB="$(du -sk "${DEB_STAGING}" | cut -f1)"

cat > "${DEB_STAGING}/DEBIAN/control" <<EOF
Package: agenttower-control-panel
Version: ${APP_VERSION}
Section: devel
Priority: optional
Architecture: amd64
Maintainer: ${DEB_MAINTAINER}
Installed-Size: ${INSTALLED_SIZE_KB}
Depends: libgtk-3-0 (>= 3.24), libglib2.0-0 (>= 2.66)
Description: AgentTower Flutter Desktop Control Panel
 Local-first operator UI for agenttowerd. Connects only to a per-user
 Unix-domain socket; no network listener (FR-001 / FR-060).
Homepage: https://opensoft.one/agenttower
EOF

chmod 0755 "${DEB_STAGING}/DEBIAN"
DEB_OUT="${OUT_DIR}/agenttower-control-panel_${APP_VERSION}_amd64.deb"
echo "==> dpkg-deb --build → ${DEB_OUT}"
dpkg-deb --root-owner-group --build "${DEB_STAGING}" "${DEB_OUT}" >/dev/null

# ----- 7. GPG signing ---------------------------------------------------
if [[ -n "${GPG_SIGN_KEY:-}" ]]; then
  if ! command -v gpg >/dev/null 2>&1; then
    echo "ERROR: GPG_SIGN_KEY set but gpg not on PATH." >&2
    exit 2
  fi
  echo "==> gpg --detach-sign --armor -u ${GPG_SIGN_KEY}"
  for artifact in "${APPIMAGE_OUT}" "${DEB_OUT}"; do
    [[ -f "${artifact}" ]] || continue
    rm -f "${artifact}.asc"
    gpg --batch --yes --detach-sign --armor -u "${GPG_SIGN_KEY}" -o "${artifact}.asc" "${artifact}"
  done
else
  echo "WARN: GPG_SIGN_KEY unset — artifacts are unsigned. Set GPG_SIGN_KEY=<key> for releases (R-13)." >&2
fi

# ----- 8. Report --------------------------------------------------------
echo ""
echo "=== Linux packaging complete ==="
[[ -f "${APPIMAGE_OUT}" ]] && echo "  AppImage : ${APPIMAGE_OUT}"
[[ -f "${APPIMAGE_OUT}.asc" ]] && echo "  + sig    : ${APPIMAGE_OUT}.asc"
echo "  .deb     : ${DEB_OUT}"
[[ -f "${DEB_OUT}.asc" ]] && echo "  + sig    : ${DEB_OUT}.asc"
echo ""
