from pathlib import Path

p = Path('app/src/main/java/com/fabdata/app/ForecastMemoryOverlay.kt')
s = p.read_text(encoding='utf-8')

if 'forecast_capture_attempt' in s:
    print('slot store already patched')
    raise SystemExit(0)

def once(old, new):
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f'expected one match, got {n}: {old[:80]}')
    s = s.replace(old, new, 1)

once(
'    private const val LEGACY_TRIGGER = "trg_fabdata_forecast_memory_insert"\n    private const val TRIGGER = "trg_fabdata_forecast_memory_insert_v2"\n',
'    private const val LEGACY_TRIGGER = "trg_fabdata_forecast_memory_insert"\n    private const val TRIGGER = "trg_fabdata_forecast_memory_insert_v2"\n    private const val ATTEMPT_TABLE = "forecast_capture_attempt"\n    private const val ATTEMPT_RETENTION_MS = 7L * 24L * 60L * 60L * 1000L\n'
)

once(
'''        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_slot ON $TABLE(reference_key, capture_slot_10m, target_ts)"
        )

        // v2 is a versioned migration.''',
'''        sql.execSQL(
            "CREATE INDEX IF NOT EXISTS idx_forecast_memory_ref_slot ON $TABLE(reference_key, capture_slot_10m, target_ts)"
        )
        sql.execSQL(
            """
            CREATE TABLE IF NOT EXISTS $ATTEMPT_TABLE (
                reference_key TEXT NOT NULL,
                capture_slot_10m INTEGER NOT NULL,
                trigger TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                finished_at INTEGER,
                success INTEGER,
                detail TEXT,
                PRIMARY KEY(reference_key, capture_slot_10m)
            )
            """.trimIndent()
        )

        // v2 is a versioned migration.'''
)

old = '''    fun hasCaptureSlot(sql: SQLiteDatabase, referenceKey: String, timestamp: Long): Boolean {
        ensure(sql)
        val slot = captureSlot10m(timestamp)
        return sql.rawQuery(
            """
            SELECT 1 FROM $TABLE
            WHERE reference_key=?
              AND COALESCE(capture_slot_10m, (issued_at / ?) * ?) = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(
                referenceKey, FORECAST_CAPTURE_SLOT_MS.toString(), FORECAST_CAPTURE_SLOT_MS.toString(), slot.toString()
            )
        ).use { it.moveToFirst() }
    }
}
'''
new = '''    fun hasCaptureSlot(sql: SQLiteDatabase, referenceKey: String, timestamp: Long): Boolean {
        ensure(sql)
        return hasCaptureSlotValue(sql, referenceKey, captureSlot10m(timestamp))
    }

    private fun hasCaptureSlotValue(sql: SQLiteDatabase, referenceKey: String, slot: Long): Boolean =
        sql.rawQuery(
            """
            SELECT 1 FROM $TABLE
            WHERE reference_key=?
              AND COALESCE(capture_slot_10m, (issued_at / ?) * ?) = ?
            LIMIT 1
            """.trimIndent(),
            arrayOf(referenceKey, FORECAST_CAPTURE_SLOT_MS.toString(), FORECAST_CAPTURE_SLOT_MS.toString(), slot.toString())
        ).use { it.moveToFirst() }

    fun captureSlotClosed(sql: SQLiteDatabase, referenceKey: String, timestamp: Long): Boolean {
        ensure(sql)
        val slot = captureSlot10m(timestamp)
        if (hasCaptureSlotValue(sql, referenceKey, slot)) return true
        return sql.rawQuery(
            "SELECT 1 FROM $ATTEMPT_TABLE WHERE reference_key=? AND capture_slot_10m=? LIMIT 1",
            arrayOf(referenceKey, slot.toString())
        ).use { it.moveToFirst() }
    }

    /** Atomically reserves one automatic provider call for this canonical 10-minute slot. */
    fun tryClaimCaptureSlot(
        sql: SQLiteDatabase,
        referenceKey: String,
        timestamp: Long,
        trigger: String
    ): Long? {
        ensure(sql)
        val slot = captureSlot10m(timestamp)
        if (hasCaptureSlotValue(sql, referenceKey, slot)) return null
        sql.delete(ATTEMPT_TABLE, "capture_slot_10m<?", arrayOf((slot - ATTEMPT_RETENTION_MS).toString()))
        val values = ContentValues().apply {
            put("reference_key", referenceKey)
            put("capture_slot_10m", slot)
            put("trigger", trigger)
            put("started_at", System.currentTimeMillis())
        }
        val inserted = sql.insertWithOnConflict(ATTEMPT_TABLE, null, values, SQLiteDatabase.CONFLICT_IGNORE)
        return slot.takeIf { inserted != -1L }
    }

    fun finishCaptureSlot(
        sql: SQLiteDatabase,
        referenceKey: String,
        slot: Long,
        success: Boolean,
        detail: String
    ) {
        ensure(sql)
        val values = ContentValues().apply {
            put("finished_at", System.currentTimeMillis())
            put("success", if (success) 1 else 0)
            put("detail", detail.take(240))
        }
        sql.update(
            ATTEMPT_TABLE,
            values,
            "reference_key=? AND capture_slot_10m=?",
            arrayOf(referenceKey, slot.toString())
        )
    }
}
'''
once(old, new)
p.write_text(s, encoding='utf-8')
print('slot store patched')
