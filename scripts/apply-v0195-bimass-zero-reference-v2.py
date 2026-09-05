from pathlib import Path

script = Path('scripts/apply-v0195-bimass-zero-reference.py')
text = script.read_text()
old = "ridge_start = '    private fun ridgeRegression(\\n'"
new = "ridge_start = '    private fun ridgeRegression(rows: List<TrainingRow>): DoubleArray? {'"
if text.count(old) != 1:
    raise SystemExit(f'v0.19.5 marker fix expected 1 match, got {text.count(old)}')
script.write_text(text.replace(old, new, 1))

code = compile(script.read_text(), str(script), 'exec')
namespace = {'__name__': '__main__', '__file__': str(script)}
exec(code, namespace)
