from pathlib import Path

source_path = Path("tools/fix_v0215_temporal_page_navigation.py")
source = source_path.read_text(encoding="utf-8")
bad = 'g = gradle.read_text(encoding="utf-8")ng = replace_once('
good = 'g = gradle.read_text(encoding="utf-8")\ng = replace_once('
if bad not in source:
    raise SystemExit("v0.21.5 patch runner: expected syntax repair anchor missing")
source = source.replace(bad, good, 1)
exec(compile(source, str(source_path), "exec"), {"__name__": "__main__"})
