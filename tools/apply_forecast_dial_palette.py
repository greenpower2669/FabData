from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt")
text = path.read_text(encoding="utf-8")

old = '''    private fun officialBorder(sample: DialSample, night: Boolean): Int {
        val error = sample.officialError ?: return if (night) Color.rgb(150, 155, 165) else Color.rgb(150, 150, 150)
        val strength = (error / 2.5).coerceIn(0.0, 1.0).toFloat()
        val neutral = if (night) Color.rgb(150, 155, 165) else Color.rgb(155, 155, 155)
        return blend(neutral, Color.rgb(220, 40, 40), strength)
    }

    private fun comparisonFill(sample: DialSample, night: Boolean): Int {
        val official = sample.officialError
        val local = sample.localError
        if (official == null || local == null) {
            return if (night) Color.rgb(52, 55, 62) else Color.rgb(242, 243, 245)
        }
        val gain = official - local
        val strength = (abs(gain) / 1.5).coerceIn(0.0, 1.0).toFloat()
        val neutral = if (night) Color.rgb(52, 55, 62) else Color.rgb(242, 243, 245)
        return if (gain >= 0.0) {
            blend(neutral, if (night) Color.rgb(42, 105, 65) else Color.rgb(205, 242, 215), strength)
        } else {
            blend(neutral, if (night) Color.rgb(125, 67, 45) else Color.rgb(255, 221, 204), strength)
        }
    }
'''

new = '''    /*
     * Error colours deliberately use a palette that is distinct from the three needles.
     * Border = absolute error of the large weather model against the real value.
     * Background = absolute error of the Fab local model against the real value.
     * Both use the same continuous severity scale: blue -> orange -> red -> violet.
     */
    private fun officialBorder(sample: DialSample, night: Boolean): Int {
        val error = sample.officialError
            ?: return if (night) Color.rgb(130, 138, 150) else Color.rgb(170, 175, 182)
        return errorSeverityColor(error)
    }

    private fun comparisonFill(sample: DialSample, night: Boolean): Int {
        val error = sample.localError
            ?: return if (night) Color.rgb(52, 55, 62) else Color.rgb(242, 243, 245)
        return errorSeverityColor(error)
    }

    private fun errorSeverityColor(errorC: Double): Int {
        val error = errorC.coerceAtLeast(0.0)
        val blue = Color.rgb(45, 115, 205)
        val orange = Color.rgb(238, 145, 35)
        val red = Color.rgb(210, 55, 70)
        val violet = Color.rgb(120, 65, 175)

        return when {
            error <= 0.75 -> blend(blue, orange, (error / 0.75).toFloat())
            error <= 1.50 -> blend(orange, red, ((error - 0.75) / 0.75).toFloat())
            error <= 2.50 -> blend(red, violet, ((error - 1.50) / 1.00).toFloat())
            else -> violet
        }
    }
'''

if old in text:
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("Applied blue -> orange -> red -> violet dial palette")
elif "private fun errorSeverityColor(errorC: Double): Int" in text:
    print("Palette already applied")
else:
    raise SystemExit("Expected dial colour block not found; refusing broad rewrite")
