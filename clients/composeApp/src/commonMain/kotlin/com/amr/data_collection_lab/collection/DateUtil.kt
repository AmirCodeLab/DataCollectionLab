package com.amr.data_collection_lab.collection

/**
 * UTC-day <-> ISO date conversion for the Material date picker, which speaks
 * epoch milliseconds at UTC midnight. Pure calendar arithmetic (Howard
 * Hinnant's civil-date algorithms) — no timezone involvement, no kotlinx-datetime.
 */

private const val MILLIS_PER_DAY = 86_400_000L

fun epochMillisToIsoDate(millis: Long): String {
    var z = millis.floorDiv(MILLIS_PER_DAY) + 719_468
    val era = (if (z >= 0) z else z - 146_096).floorDiv(146_097)
    val doe = z - era * 146_097
    val yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
    val y = yoe + era * 400
    val doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
    val mp = (5 * doy + 2) / 153
    val d = doy - (153 * mp + 2) / 5 + 1
    val m = if (mp < 10) mp + 3 else mp - 9
    val year = if (m <= 2) y + 1 else y
    return "${year.toString().padStart(4, '0')}-" +
        "${m.toString().padStart(2, '0')}-" +
        d.toString().padStart(2, '0')
}

fun isoDateToEpochMillis(iso: String?): Long? {
    val parts = iso?.split("-") ?: return null
    if (parts.size != 3) return null
    val y = parts[0].toLongOrNull() ?: return null
    val m = parts[1].toLongOrNull() ?: return null
    val d = parts[2].toLongOrNull() ?: return null
    if (m !in 1..12 || d !in 1..31) return null
    val yy = if (m <= 2) y - 1 else y
    val era = (if (yy >= 0) yy else yy - 399).floorDiv(400)
    val yoe = yy - era * 400
    val mp = if (m > 2) m - 3 else m + 9
    val doy = (153 * mp + 2) / 5 + d - 1
    val doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
    return (era * 146_097 + doe - 719_468) * MILLIS_PER_DAY
}
