disposition: fix

Unavailable inputs: engine state/spec/comp-diff reports and a separate QUALITY BAR card. This is a manual comparison with the approved image and documented brief, not an automated fidelity pass. Desktop capture dimensions exclude browser framing (parent confirmed a 1440×1000 DOM viewport); all four required captures are valid.

## persistence

Pass for the manual review packet: PRODUCT.md, the approved image, and the recorded user choice exist. DESIGN.md and docs/design/rules-surface.md remain explicitly pre-implementation documents; the scheduled documenter must replace their obsolete pause/status language and record final tokens, states, adaptations, and checks before delivery. Engine phase closure and numerical reproduction quality are unproven and are not claimed here. The approved choice predates this implementation, so no new concept roll or approval round is warranted.

## fidelity

| Element | Verdict | Evidence |
| --- | --- | --- |
| Forest header, identity, search, desktop PDF action | match | Same placement, hierarchy, color roles, and readable controls as the approved comp. |
| Desktop chapter rail and local contents | match | Ten numbered chapters, forest active chapter, ruled local navigation, olive active subsection and green marker. |
| Chapter heading and breadcrumb at document top | adaptation | The full-page captures show the real first section; the D12 viewport is a deep link. This follows the canonical source and the brief's explicit adaptation. |
| Mobile chapter context at a deep link | missing | mobile.png shows the header immediately followed by the D12 subsection, with no chapter name or short return path. The approved phone comp and rules-surface.md explicitly include that context. The breadcrumb and local contents at the top of the document do not preserve it here. |
| Single-column mobile reading and persistent bottom actions | match | Search, chapters, PDF, and saved-version state retain the approved structure. Canonical content remains readable without horizontal page overflow in the captures. |
| TYPE | adaptation | Locally hosted PT Sans and PT Sans Narrow Bold follow DESIGN.md. D12 is an h3 in the real hierarchy, as documented in the brief; source heading levels are preserved. |
| MATERIAL | adaptation | Flat paper, olive surfaces, thin rules and restrained ochre notes follow DESIGN.md's explicit instruction not to reproduce raster irregularities. Source illustrations remain actual images. |
| GROUND | match | The implementation uses the approved documented paper #F5F3EA, forest #30483B and olive #E9EBDD. No competing visual palette is introduced. |
| Table and editorial warning | match | Two-column ruled table, restrained olive heading, distinct ochre warning, consistent semantic label. |
| Longer content, lists, captions and source images | adaptation | AGENTS.md gives the original rules priority over the shortened demonstration copy; the brief records this adaptation. Full-page captures show the supplied images and continued reading flow. |

## ceiling

The reading-first visual world is adequately expressed through the condensed identity, disciplined columns, ruled tables and restrained semantic colors. Extra ornament, physical texture, or entrance motion would not improve this product. Its remaining ceiling is clear wayfinding and consistent interaction feedback.

## material_fixes

1. Fidelity / mobile wayfinding — Restore visible compact chapter context and a return path while reading an anchored subsection on mobile (the approved “06 · Повреждения и тесты” treatment is the reference); verify the D12 deep-link viewport retains that context without covering its heading.
2. Product / search — Unify fuzzy matching in assets/search.js: search() allows two edits for stems of at least eight characters, while hit() allows only one, so excerpt() can select an unrelated beginning and no text is highlighted. Reproduced read-only with “транпортиовка” matching “транспортировка”: one result, hit=false, unrelated excerpt. Use the same predicate for ranking, snippet selection and highlighting.
3. Accessibility / focus — The global #925C0A focus outline has only 1.78:1 contrast against the #30483B header, so keyboard focus on the brand, menu and other header controls is weak. Add a contrasting focus treatment for dark surfaces (at least 3:1 against the adjacent surface), retaining the current visible light-surface treatment; verify header and mobile menu focus.

## keep

Keep the approved paper/forest/olive system, source-complete rules and illustrations, restrained tables and warnings, local fonts, continuous reading flow, and visible offline revision; do not compress canonical content to recreate the demonstration screenshot's height.
