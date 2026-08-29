package com.dcp.core.sync

import kotlin.random.Random

/**
 * ULID generator (https://github.com/ulid/spec): 48-bit millisecond timestamp +
 * 80 bits of randomness, Crockford base32, lexicographically sortable.
 *
 * Monotonic within a process: two ULIDs minted in the same millisecond increment
 * the random component so op ids on one device never sort against insertion
 * order. `opId` is the sync idempotency key (sync protocol §2), so collisions
 * must be impossible in practice.
 */
object Ulid {
    private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

    private var lastTime = -1L
    private val lastRandom = IntArray(16) // 16 base32 digits = 80 bits

    fun generate(timeMillis: Long, random: Random = Random.Default): String {
        val digits = CharArray(26)

        var t = timeMillis
        for (i in 9 downTo 0) {
            digits[i] = ALPHABET[(t and 0x1F).toInt()]
            t = t ushr 5
        }

        if (timeMillis == lastTime) {
            // same millisecond: increment the previous randomness by one
            var i = 15
            while (i >= 0) {
                lastRandom[i] = (lastRandom[i] + 1) and 0x1F
                if (lastRandom[i] != 0) break
                i--
            }
        } else {
            lastTime = timeMillis
            for (i in 0 until 16) lastRandom[i] = random.nextInt(32)
        }
        for (i in 0 until 16) digits[10 + i] = ALPHABET[lastRandom[i]]

        return digits.concatToString()
    }
}
