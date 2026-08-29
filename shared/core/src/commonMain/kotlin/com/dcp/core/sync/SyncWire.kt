package com.dcp.core.sync

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement

/** Wire types for /api/v1/sync (specs/sync-protocol-v0.1.md §2, §4, §5). */

val SyncJson: Json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
}

@Serializable
data class WireOp(
    val opId: String,
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val kind: String,
    val path: String? = null,
    val value: JsonElement? = null,
    val deviceId: String,
    val actorId: String? = null,
    val counter: Long,
    val wallClock: String,
)

@Serializable
data class WirePushRequest(val deviceId: String, val ops: List<WireOp>)

/**
 * POST /api/v1/devices (sync §4). Idempotent: registering an id the server
 * already knows returns `already_registered`, which is success.
 */
@Serializable
data class WireDeviceRegisterRequest(
    val deviceId: String,
    val platform: String,
    val osVersion: String? = null,
    val appVersion: String? = null,
)

@Serializable
data class WireDeviceRegisterResponse(
    val deviceId: String,
    val status: String,
)

/**
 * Body of a failed registration. `reason` is the contract — project_not_found,
 * project_ambiguous, project_mismatch, device_revoked — and `message` says what
 * to do about it. Reported verbatim so a developer sees "the database was never
 * seeded" rather than a bare status code.
 */
@Serializable
data class WireErrorDetail(
    val reason: String,
    val message: String = "",
)

@Serializable
data class WireErrorBody(val detail: WireErrorDetail? = null)

@Serializable
data class WireRejectedOp(val opId: String? = null, val reason: String)

@Serializable
data class WirePushResponse(
    val accepted: List<String> = emptyList(),
    val rejected: List<WireRejectedOp> = emptyList(),
    val serverCursor: Long = 0,
)

@Serializable
data class WirePulledOp(
    val opId: String,
    val submissionId: String,
    val formId: String,
    val formVersion: Int,
    val kind: String,
    val path: String? = null,
    val value: JsonElement? = null,
    val deviceId: String,
    val actorId: String? = null,
    val counter: Long,
    val wallClock: String,
    val serverSeq: Long,
)

@Serializable
data class WirePullResponse(
    val ops: List<WirePulledOp> = emptyList(),
    // Tombstones are carried but not applied yet — repeat/submission deletion
    // has no local handling in this slice.
    val tombstones: List<JsonElement> = emptyList(),
    val nextCursor: Long,
    val hasMore: Boolean = false,
)
