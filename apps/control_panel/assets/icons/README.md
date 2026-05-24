# Severity + Navigation Icons

This directory holds icon assets referenced by the FEAT-012 UI.

## Severity icons (research R-15)

Per R-15, the four severity levels (`info`, `warning`, `high`, `critical`) are rendered with both a unique color AND a unique icon, so colorblind operators receive equivalent information.

Material Symbols used (no separate SVG asset needed; Flutter ships these):
- `info` → `Icons.info_outlined`
- `warning` → `Icons.warning_amber_outlined`
- `high` → `Icons.priority_high`
- `critical` → `Icons.error`

If we later need branded variants, drop SVGs in this directory and reference via `flutter_svg` (not yet a dependency).

## Workspace navigation icons (T046 + Round-3 R-39)

Per R-39, each of the four top-level workspaces gets a distinct icon + color accent. Material Symbols proposal:
- Agent Operations → `Icons.dns_outlined`
- Project and Specs → `Icons.workspaces_outlined`
- Testing and Demo → `Icons.science_outlined`
- Settings → `Icons.settings_outlined`

Color accents are pulled from the R-15 palette but kept in a separate `accent` namespace so they never collide with severity colors.

## Placeholder

This directory is a stub at T007 (Phase 1). Phase 2 task T028 (theme tokens) wires the icon constants in `lib/ui/theme/icon_tokens.dart`.
