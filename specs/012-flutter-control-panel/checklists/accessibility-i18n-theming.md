# Accessibility, Internationalization & Theming Requirements Quality Checklist: Flutter Desktop Control Panel

**Purpose**: Validate that accessibility (FR-066), internationalization (FR-067), and theming (FR-009) requirements are clear, complete, consistent, and measurable. Tests the requirements themselves.
**Created**: 2026-05-23
**Feature**: [spec.md](../spec.md)
**Scope**: WCAG 2.1 AA-equivalent baseline, English-only-with-i18n-layer commitment, theme/density enumeration, color/contrast, focus order, semantic labelling.

## Accessibility Scope & Baseline (FR-066)

- [ ] CHK001 - Is the "WCAG 2.1 AA-equivalent" baseline (FR-066) defined by enumerated success criteria the app commits to (e.g. 1.3.1 Info & Relationships, 1.4.3 Contrast, 2.1.1 Keyboard, 2.4.3 Focus Order, 2.4.7 Focus Visible, 4.1.2 Name/Role/Value), or only by name? [Completeness, Spec §FR-066]
- [ ] CHK002 - Does FR-066 enumerate the surfaces in scope (every interactive control, every status indicator, every error message, every notification) or leave the scope as implicit? [Completeness, Spec §FR-066]
- [ ] CHK003 - Is the explicit exclusion of "certified screen-reader pass in MVP" (FR-066) reconciled with the requirement that "interactive controls MUST carry semantic labels sufficient to make a future screen-reader pass additive" — i.e. is the label requirement itself testable without a screen reader? [Clarity, Spec §FR-066]
- [ ] CHK004 - Are color-contrast requirements (4.5:1 normal text, 3:1 large text and meaningful non-text) tied to the color tokens used by Light, Dark, and System themes (FR-009) such that each theme inherits the same constraint? [Consistency, Spec §FR-009 / §FR-066]
- [ ] CHK005 - Is "meaningful non-text contrast" (FR-066) enumerated against the spec's own non-text signals — severity color (attention queue, drift badge), validation badge color, master active/inactive badge, daemon health indicator? [Coverage, Spec §FR-066 / §FR-052 / §FR-025]

## Focus, Keyboard Operability, and Visible-Focus (interplay with FR-075)

- [ ] CHK006 - Does FR-066 define focus-order requirements for compound widgets (lists with row-level actions, cards with multiple quick actions, the handoff preview with sectioned content)? [Completeness, Gap, Spec §FR-066]
- [ ] CHK007 - Are visible-focus requirements specified to remain visible when the operator's pointer is also on a different control (focus-vs-hover divergence)? [Coverage, Gap]
- [ ] CHK008 - Are requirements present for trap-free focus on modal/confirmation surfaces (e.g. Remove project FR-077, supersede confirmation, contract-version banner)? [Coverage, Gap, Spec §FR-066]

## Semantic Labelling

- [ ] CHK009 - Are accessible-name patterns specified for each badge type (validation badge, drift badge, attention severity, master active/inactive, repo state) so a future screen-reader reads them as text rather than as icons? [Completeness, Gap, Spec §FR-066]
- [ ] CHK010 - Are accessible-name patterns specified for icon-only quick actions on the project card (FR-025) and for icon-only actions in the attention queue (FR-052)? [Completeness, Gap]
- [ ] CHK011 - Are accessible-name patterns specified for severity colors so colorblind operators receive equivalent information (icon + text + color, not color alone)? [Coverage, Spec §FR-052 / §FR-066]
- [ ] CHK012 - Are accessible-name patterns specified for the in-app rendered markdown view's headings, lists, and code blocks (FR-079) so they map to platform a11y headings and lists? [Coverage, Gap]

## Internationalization (FR-067)

- [ ] CHK013 - Does FR-067 enumerate which string categories MUST route through the i18n layer (UI labels, error messages, log strings, notification text, command-palette entries, OS-native notification text) or only state "all user-facing strings"? [Completeness, Spec §FR-067]
- [ ] CHK014 - Are date, time, number, and duration formatting requirements specified to flow through the localization layer (FR-067) rather than being hard-coded? [Coverage, Gap]
- [ ] CHK015 - Are requirements present for pluralization handling (e.g. "1 master / 2 masters", "1 finding / N findings") that does not collapse on locales with non-binary plural rules? [Coverage, Gap]
- [ ] CHK016 - Are requirements present for right-to-left layout readiness (mirroring), or is layout-direction support explicitly excluded? [Coverage, Gap, Spec §FR-067]
- [ ] CHK017 - Are requirements present for locale-sensitive sorting in list views (FR-078) — does sort respect the current locale or always use a fixed comparator? [Clarity, Gap]
- [ ] CHK018 - Is the i18n-layer technology choice (`flutter_localizations`/ARB or equivalent) named as an example or as a requirement? [Clarity, Spec §FR-067]
- [ ] CHK019 - Are requirements present for what happens when a new string is added to the codebase but not to the English ARB — does the app fail to build, fall back to the key, or silently render empty? [Coverage, Gap]

## Theming (FR-009)

- [ ] CHK020 - Is "Light" defined by a color token set (not just by name) so it can be measured against the contrast requirement in FR-066? [Completeness, Gap, Spec §FR-009 / §FR-066]
- [ ] CHK021 - Is "Dark" similarly defined by a color token set with the same contrast guarantee? [Completeness, Gap, Spec §FR-009 / §FR-066]
- [ ] CHK022 - Is "System" defined to track the OS theme live (per Q12 clarification) AND to track OS-level accent colors / high-contrast preferences where the host platform exposes them? [Clarity, Gap, Spec §FR-009]
- [ ] CHK023 - Are theme requirements specified for transient surfaces (toasts, tooltips, OS-native notifications) so they remain contrast-compliant regardless of theme? [Coverage, Gap]
- [ ] CHK024 - Does FR-009 require that theme changes apply without app restart, or is restart-required behavior acceptable? [Clarity, Gap]

## Density (FR-009)

- [ ] CHK025 - Is "Comfortable" defined by a concrete row-height / padding token set, or only by name? [Clarity, Gap, Spec §FR-009]
- [ ] CHK026 - Is "Compact" defined the same way, and does density commit to maintain WCAG-equivalent touch/click target sizes (FR-066)? [Consistency, Spec §FR-009 / §FR-066]
- [ ] CHK027 - Are density requirements specified to apply consistently across all FR-063 list views, or per-view? [Coverage, Gap]

## OS-Native Notifications & A11y

- [ ] CHK028 - Are accessibility requirements present for the OS-native notification content (FR-058) — does the i18n layer flow through OS notifications? [Coverage, Spec §FR-058 / §FR-067]
- [ ] CHK029 - Are requirements present for how OS-native notifications represent severity colors / icons on platforms where the OS dictates the notification chrome? [Coverage, Gap, Spec §FR-058]

## Settings Surface (theming/i18n/accessibility configuration)

- [ ] CHK030 - Is the Settings surface's discoverability of accessibility options (theme, density, OS notification toggle, notification grouping toggle) specified — is there a dedicated "Display & Accessibility" group? [Coverage, Gap, Spec §FR-009]
- [ ] CHK031 - Are requirements present for the keyboard-only path through Settings (e.g. arrow keys to focus the row, Enter to toggle, Esc to close) consistent with FR-075? [Consistency, Spec §FR-009 / §FR-075]

## Scenario Class Coverage (A11y/I18n/Theming)

- [ ] CHK032 - Are accessibility requirements present for Alternate flows (e.g. operating without a mouse, operating with high-contrast OS theme active)? [Coverage, Gap]
- [ ] CHK033 - Are accessibility requirements present for Exception flows (e.g. how an error message announces itself, how a focus-trapped modal returns focus after dismissal)? [Coverage, Gap]
- [ ] CHK034 - Are accessibility requirements present for Recovery flows (e.g. after daemon reconnect, is focus returned to the last interactive element)? [Coverage, Gap]
- [ ] CHK035 - Are accessibility Non-Functional requirements covered by at least one SC, or is the only commitment qualitative (FR-066 baseline) with no measurable success criterion? [Coverage, Gap, Spec §Success Criteria / §FR-066]

## Measurability

- [ ] CHK036 - Can "WCAG 2.1 AA-equivalent" (FR-066) be objectively audited without a certified screen-reader pass — is the audit method (automated + manual checks) named in the spec? [Measurability, Spec §FR-066]
- [ ] CHK037 - Can "translation drop-in" (FR-067) be measured — e.g. is there a target language-add time, or a count of source-code changes required (zero)? [Measurability, Gap, Spec §FR-067]
- [ ] CHK038 - Can "theme MUST track OS theme" (FR-009 + Q12) be measured — is there a specific switch-time budget when the OS theme changes mid-session? [Measurability, Gap]

## Ambiguities & Conflicts

- [ ] CHK039 - Does the absence of a screen-reader-pass commitment (FR-066) leave open whether SC-012's "90% operator identification from card-level info alone" includes operators who use assistive technology? [Ambiguity, Spec §FR-066 / §SC-012]
- [ ] CHK040 - Does the i18n English-only commitment (FR-067) conflict with the in-app rendering of markdown documents (FR-079) — i.e. do PRDs/specs need their own localization layer, or is document content always rendered in the source language? [Ambiguity, Spec §FR-067 / §FR-079]
- [ ] CHK041 - Is there a conflict between FR-009 ("density Comfortable / Compact") and FR-066 (4.5:1 contrast, accessible click target sizes) at the smallest Compact density? [Conflict, Gap, Spec §FR-009 / §FR-066]

## Round 2 — Post-plan re-verification (2026-05-23)

Re-checks that `research.md` R-08 (i18n), R-15 (severity palette), R-11 (window), and plan.md tech-context close the Round-1 a11y/i18n/theming gaps.

- [ ] CHK042 - Does research R-08 close CHK013 (i18n string categories) — note: still says "all user-facing strings"; granular categorization not present? [Closure-check, Round-1 CHK013]
- [ ] CHK043 - Does research R-08 close CHK018 (i18n tech choice) — flutter_localizations + ARB is named as a requirement now? [Closure-check, Round-1 CHK018]
- [ ] CHK044 - Does research R-15 close CHK020 + CHK021 (Light + Dark color tokens with contrast) by naming concrete hex values verified WCAG AA per theme? [Closure-check, Round-1 CHK020/021]
- [ ] CHK045 - Does research R-15 close CHK005 (meaningful non-text contrast enumerated)? [Closure-check, Round-1 CHK005]
- [ ] CHK046 - Are Round-1 gaps NOT closed by the plan: WCAG enumerated success criteria (CHK001), label scope per surface (CHK002), focus-order for compound widgets (CHK006), modal trap-free focus (CHK008), per-badge accessible names (CHK009-012), pluralization (CHK015), RTL readiness (CHK016), locale-sensitive sorting (CHK017), missing-string fallback (CHK019), high-contrast variant (R-15 doesn't add one — confirmed deferred)? [Gap-tracking, Round-1 multi-CHK]
- [ ] CHK047 - Are there NEW a11y/i18n/theming concerns the plan artifacts introduce (e.g. the doctor's surface needs i18n; the command palette needs locale-aware fuzzy search)? [Coverage, Plan §Primary Dependencies / Research R-08]
