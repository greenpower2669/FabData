from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'app/src/main/java/com/fabdata/app/MainActivity.kt'
text = path.read_text(encoding='utf-8')

replacements = [
    (
        'val oldCenter = clampCenter(previewCenter, oldSpan)',
        'val oldCenter = clampCenterIn(navigatorWindow, previewCenter, oldSpan)'
    ),
    (
        'previewCenter = clampCenter(zoomAnchoredCenter + panShift, newSpan)',
        'previewCenter = clampCenterIn(navigatorWindow, zoomAnchoredCenter + panShift, newSpan)'
    ),
    (
        '''navigatorCenter = clampCenterIn(bounds, navigatorCenter + deltaTs, navigatorSpan)\n                                previewCenter = navigatorCenter''',
        '''val nextCenter = clampCenterIn(bounds, navigatorCenter + deltaTs, navigatorSpan)\n                                navigatorCenter = nextCenter\n                                previewCenter = nextCenter'''
    ),
    (
        '''navigatorCenter = clampCenterIn(bounds, target, navigatorSpan)\n                                previewCenter = navigatorCenter''',
        '''val nextCenter = clampCenterIn(bounds, target, navigatorSpan)\n                                navigatorCenter = nextCenter\n                                previewCenter = nextCenter'''
    ),
]
for old, new in replacements:
    if old in text:
        text = text.replace(old, new)

# No stale identifiers from the single-resolution overview may survive.
text = text.replace('chartOverviewSampleMap', 'chartExplorationOverviewSampleMap')
text = text.replace('overviewSampleMap', 'explorationOverviewSampleMap')

path.write_text(text, encoding='utf-8')
print('v0.21 compile guards applied')
