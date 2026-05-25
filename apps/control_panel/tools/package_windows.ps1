# Windows packaging — MSIX (sideload, no Microsoft Store at MVP)
# (T148, research R-13 + R-35).
#
# Produces:
#   <OUT_DIR>\agenttower-control-panel-<version>.msix
# Driven by the `msix` Dart pub package (https://pub.dev/packages/msix), which
# wraps signtool + makepri + the Windows App Packaging tools. The config is
# kept in pubspec.yaml under `msix_config:` so this script stays declarative.
#
# Prerequisites (operator side — unverified by the Linux bench):
#   - Windows 10 1809+ or Windows 11 build host
#   - Flutter SDK on PATH (3.27 per FVM pin) with windows desktop enabled
#   - Opensoft EV code-signing certificate (reused from agenttowerd CA per R-35)
#     installed in the user's certificate store (Personal\Certificates) OR
#     accessible via a .pfx file path passed via $env:CERTIFICATE_PATH
#   - Windows 10/11 SDK (provides signtool.exe + makepri.exe)
#
# Environment variables (PowerShell $env: form):
#   $env:FLUTTER             path/name of flutter executable (default: flutter)
#   $env:OUT_DIR             destination dir (default: build\dist\windows)
#   $env:APP_VERSION         override version (default: parsed from pubspec.yaml)
#   $env:CERTIFICATE_PATH    full path to .pfx (omit if cert is in cert store)
#   $env:CERTIFICATE_PASSWORD password for .pfx (only with CERTIFICATE_PATH)
#   $env:PUBLISHER           full DN of signing cert subject; MUST exactly match
#                            the cert's CN= field (e.g.
#                            "CN=Opensoft Inc, O=Opensoft Inc, L=Wellington, S=Wellington, C=NZ")
#   $env:SKIP_SIGNING        "1" to skip signtool (dev builds only — Windows
#                            will refuse to install an unsigned MSIX without
#                            sideload+developer-mode flags)
#
# Exit status:
#   0 on success
#   non-zero with a single human-readable error line on any failure

$ErrorActionPreference = 'Stop'

# ----- 1. Resolve paths --------------------------------------------------
$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppDir = Resolve-Path (Join-Path $ToolsDir '..')

if (-not (Test-Path (Join-Path $AppDir 'pubspec.yaml'))) {
  Write-Error "ERROR: cannot locate pubspec.yaml relative to $($MyInvocation.MyCommand.Path) (expected $AppDir\pubspec.yaml)"
}

$Flutter = if ($env:FLUTTER) { $env:FLUTTER } else { 'flutter' }
if (-not (Get-Command $Flutter -ErrorAction SilentlyContinue)) {
  Write-Error "ERROR: $Flutter not on PATH. Set `$env:FLUTTER=C:\path\to\flutter.bat or install Flutter >= 3.27."
}

$SkipSigning = if ($env:SKIP_SIGNING -eq '1') { $true } else { $false }

if (-not $SkipSigning) {
  $Signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
  if (-not $Signtool) {
    Write-Error "ERROR: signtool.exe not on PATH (Windows 10/11 SDK required). Set `$env:SKIP_SIGNING=1 for unsigned dev builds."
  }
}

# ----- 2. Resolve version ------------------------------------------------
$AppVersion = $env:APP_VERSION
if (-not $AppVersion) {
  $VersionLine = Select-String -Path (Join-Path $AppDir 'pubspec.yaml') -Pattern '^version:\s*(\S+)' | Select-Object -First 1
  if ($VersionLine) {
    $AppVersion = ($VersionLine.Matches.Groups[1].Value -split '\+')[0]
  }
}
if (-not $AppVersion) {
  Write-Error "ERROR: could not parse version from pubspec.yaml"
}

# MSIX expects a 4-part version (W.X.Y.Z); pad the pubspec semver as needed.
$VersionParts = $AppVersion.Split('.')
while ($VersionParts.Count -lt 4) { $VersionParts += '0' }
$MsixVersion = ($VersionParts[0..3] -join '.')

$OutDir = if ($env:OUT_DIR) { $env:OUT_DIR } else { Join-Path $AppDir 'build\dist\windows' }
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

# ----- 3. Validate publisher --------------------------------------------
if (-not $SkipSigning -and -not $env:PUBLISHER) {
  Write-Error "ERROR: `$env:PUBLISHER must be set to the signing certificate's full CN= subject (e.g. 'CN=Opensoft Inc, O=Opensoft Inc, L=Wellington, S=Wellington, C=NZ'). Set `$env:SKIP_SIGNING=1 for unsigned dev builds."
}

# ----- 4. flutter build --------------------------------------------------
Write-Host "==> flutter build windows --release (version $AppVersion)"
Push-Location $AppDir
try {
  & $Flutter build windows --release
  if ($LASTEXITCODE -ne 0) { Write-Error "flutter build failed with exit $LASTEXITCODE" }
} finally {
  Pop-Location
}

$BuildOut = Join-Path $AppDir 'build\windows\x64\runner\Release'
if (-not (Test-Path $BuildOut)) {
  Write-Error "ERROR: expected Flutter Release dir at $BuildOut not present after build."
}

# ----- 5. Build MSIX via the msix pub package ----------------------------
# The msix package reads its config from pubspec.yaml's `msix_config:` block
# (committed alongside this script). It already handles makepri + signtool
# invocation; we just pass the override flags it accepts.
$MsixArgs = @(
  'run', 'msix:create',
  '--version', $MsixVersion,
  '--output-path', $OutDir,
  '--output-name', "agenttower-control-panel-$AppVersion"
)

if ($SkipSigning) {
  Write-Warning "SKIP_SIGNING=1 — producing unsigned MSIX. Windows will refuse to install without sideload + developer mode."
  $MsixArgs += '--no-sign-msix'
} else {
  if ($env:CERTIFICATE_PATH) {
    $MsixArgs += '--certificate-path', $env:CERTIFICATE_PATH
    if ($env:CERTIFICATE_PASSWORD) {
      $MsixArgs += '--certificate-password', $env:CERTIFICATE_PASSWORD
    }
  }
  $MsixArgs += '--publisher', $env:PUBLISHER
}

Write-Host "==> dart $($MsixArgs -join ' ')"
Push-Location $AppDir
try {
  & dart @MsixArgs
  if ($LASTEXITCODE -ne 0) { Write-Error "msix:create failed with exit $LASTEXITCODE" }
} finally {
  Pop-Location
}

# ----- 6. Verify (when signed) ------------------------------------------
$MsixOut = Join-Path $OutDir "agenttower-control-panel-$AppVersion.msix"
if (-not (Test-Path $MsixOut)) {
  Write-Error "ERROR: expected MSIX artifact at $MsixOut not present after msix:create."
}

if (-not $SkipSigning) {
  Write-Host "==> signtool verify /pa"
  & signtool.exe verify /pa /v $MsixOut
  if ($LASTEXITCODE -ne 0) { Write-Error "signtool verify failed with exit $LASTEXITCODE" }
}

# ----- 7. Report --------------------------------------------------------
Write-Host ""
Write-Host "=== Windows packaging complete ==="
Write-Host "  MSIX    : $MsixOut"
Write-Host "  Version : $AppVersion (4-part: $MsixVersion)"
if ($SkipSigning) {
  Write-Host "  Status  : UNSIGNED dev build (sideload + developer mode required to install)"
} else {
  Write-Host "  Status  : Signed (publisher: $($env:PUBLISHER))"
}
Write-Host ""
