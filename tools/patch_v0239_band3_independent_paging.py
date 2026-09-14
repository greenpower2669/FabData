from pathlib import Path

MAIN = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


main = MAIN.read_text(encoding="utf-8")

# Band 3 (exploration/training workspace) must page independently from the detailed graph.
# Upper bands still cascade on release, and detail has its own page controls.
marker = '''        selectedAnnotation = null\n    }\n\n    val temporalPageRange = explorationOverviewRange\n'''
insert = '''        selectedAnnotation = null\n    }\n\n    fun requestExplorationPage(direction: TemporalPageDirection, currentPage: LongRange) {\n        if (lowerCascadeVeil) return\n        val history = overviewDisplayBounds ?: return\n        val historySpan = (history.last - history.first).coerceAtLeast(1L)\n        val pageSpan = (currentPage.last - currentPage.first).coerceAtLeast(1L)\n            .coerceAtMost(historySpan)\n        if (pageSpan >= historySpan) return\n\n        val desiredCenter = when (direction) {\n            TemporalPageDirection.NEXT -> {\n                if (currentPage.last >= history.last) return\n                currentPage.last + pageSpan / 2L\n            }\n            TemporalPageDirection.PREVIOUS -> {\n                if (currentPage.first <= history.first) return\n                currentPage.first - pageSpan / 2L\n            }\n        }\n        val nextPage = centeredTemporalRange(desiredCenter, pageSpan, history)\n        if (nextPage.first == currentPage.first && nextPage.last == currentPage.last) return\n\n        val nextPageSpan = (nextPage.last - nextPage.first).coerceAtLeast(1L)\n        val nextCenter = nextPage.first + nextPageSpan / 2L\n        val currentWideSpan = wideOverviewRange\n            ?.let { (it.last - it.first).coerceAtLeast(nextPageSpan) }\n            ?: minOf(historySpan, maxOf(nextPageSpan * 2L, PreviewPreset.M1.spanMs))\n        val nextWide = centeredTemporalRange(nextCenter, currentWideSpan, history)\n\n        // Band 3 owns training-range selection, so page only its navigation parents.\n        // Do NOT move windowCenterTimestamp / selectedTimestamp / detailed graph here.\n        lowerCascadeAwaitingReload = true\n        lowerCascadeVeil = true\n        wideOverviewRange = nextWide\n        explorationOverviewRange = nextPage\n        temporalPageSyncCenter = nextCenter\n        temporalPageSyncToken++\n    }\n\n    val temporalPageRange = explorationOverviewRange\n'''
main = replace_once(main, marker, insert, "independent exploration page function")

main = replace_once(
    main,
    '                        onTemporalPageRequest = { direction, page ->\n'
    '                            requestTemporalPage(direction, page)\n'
    '                        },\n',
    '                        onTemporalPageRequest = { direction, page ->\n'
    '                            requestExplorationPage(direction, page)\n'
    '                        },\n',
    "history exploration paging callback",
)

MAIN.write_text(main, encoding="utf-8")
print("Applied independent band-3 paging patch")
