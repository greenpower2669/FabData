from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing patch anchor: {label}")
    return text.replace(old, new, 1)


p = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
t = p.read_text(encoding="utf-8")

# Make the hierarchy explicit in the UI.
t = replace_once(
    t,
    '"Global = mois · zoom large = jours · sélection = 6 h · détail = RAW",',
    '"1. totalité · 2. sélection du haut · 3. sélection du milieu · 4. détail RAW",',
    "cascade legend",
)

# v0.21.1 used 6x the exploration span for the middle level. With a 6-month
# exploration on a ~2-year history that collapses the middle level back to the
# entire history. Keep a meaningful intermediate window: roughly 2x the child
# span, with a one-month floor for very small exploration presets.
old_wide = """                // Niveau 1 : le giga est le seul historique complet. Sa fenêtre large
                // vaut environ 6 fois la fenêtre d'exploration (minimum 6 mois).
                val minimumWideSpan = minOf(fullSpan, PreviewPreset.M6.spanMs)
                val wideSpan = minOf(fullSpan, maxOf(previewSpan * 6L, minimumWideSpan))
                    .coerceAtLeast(previewSpan)
"""
new_wide = """                // Niveau 1 : le giga est le seul historique complet.
                // Sa sélection doit rester un VRAI niveau intermédiaire et non retomber
                // automatiquement sur tout l'historique. Le milieu vaut environ 2x
                // l'exploration, avec un plancher d'un mois pour les petits presets.
                val minimumWideSpan = minOf(fullSpan, maxOf(PreviewPreset.M1.spanMs, previewSpan))
                val desiredWideSpan = maxOf(previewSpan * 2L, minimumWideSpan)
                val wideSpan = minOf(fullSpan, desiredWideSpan).coerceAtLeast(previewSpan)
"""
t = replace_once(t, old_wide, new_wide, "meaningful middle window")

# Force the RAW detail window to stay inside the exploration window. Moving the
# top or middle band therefore carries the two lower levels with it instead of
# leaving the detailed graph behind on a former global position.
anchor = """                LaunchedEffect(wideFrom, wideTo, previewSpan) {
                    val clamped = clampCenterToRange(previewCenter, previewSpan, wideWindow)
                    if (previewCenter != clamped) previewCenter = clamped
                }
                // v0.20.8 : le bandeau exploré ne recalcule que sa fenêtre courante.
"""
replacement = """                LaunchedEffect(wideFrom, wideTo, previewSpan) {
                    val clamped = clampCenterToRange(previewCenter, previewSpan, wideWindow)
                    if (previewCenter != clamped) previewCenter = clamped
                }

                // v0.21.3 : le détail est le quatrième étage de la cascade.
                // Il ne peut jamais rester hors de la sélection du bandeau 6 h.
                LaunchedEffect(previewFrom, previewTo, viewBounds?.first, viewBounds?.last) {
                    val detail = viewBounds ?: return@LaunchedEffect
                    if (detail.first < previewFrom || detail.last > previewTo) {
                        val detailSpan = (detail.last - detail.first).coerceAtLeast(1L)
                            .coerceAtMost(previewSpan)
                        val currentDetailCenter = detail.first + (detail.last - detail.first) / 2L
                        val constrainedCenter = clampCenterToRange(
                            currentDetailCenter,
                            detailSpan,
                            previewWindow
                        )
                        onNavigate(constrainedCenter)
                    }
                }
                // v0.20.8 : le bandeau exploré ne recalcule que sa fenêtre courante.
"""
t = replace_once(t, anchor, replacement, "detail constrained to exploration")

# Clarify what each displayed level means.
t = replace_once(
    t,
    '"Navigation giga · LOD mois · historique complet",',
    '"Navigation giga · LOD mois · TOTALITÉ de l’historique",',
    "giga title",
)
t = replace_once(
    t,
    '"Zoom large · LOD jour · glisse la fenêtre de sélection",',
    '"Zoom large · LOD jour · uniquement la sélection du bandeau du haut",',
    "middle title",
)
t = replace_once(
    t,
    '"Sélection / exploration · LOD 6 h · seules ces données alimentent ce bandeau",',
    '"Sélection / exploration · LOD 6 h · limitée par le bandeau du milieu",',
    "exploration title",
)

# The hint under the third band now states explicitly that the highlighted RAW
# window is what feeds the detailed graph below.
t = replace_once(
    t,
    'Text(\n                        "max ${previewPreset.label}",',
    'Text(\n                        "fenêtre ${previewPreset.label} → détail RAW",',
    "exploration footer",
)

p.write_text(t, encoding="utf-8")

# Version bump.
p = Path("app/build.gradle.kts")
t = p.read_text(encoding="utf-8")
t = replace_once(
    t,
    '        versionCode = 48\n        versionName = "0.21.2"\n',
    '        versionCode = 49\n        versionName = "0.21.3"\n',
    "version bump",
)
p.write_text(t, encoding="utf-8")

print("FabData v0.21.3 strict cascade patch applied")
