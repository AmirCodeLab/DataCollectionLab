package com.dcp.core.media

import com.dcp.core.sync.WireWrappedKey
import kotlinx.serialization.Serializable

/** Wire types for /api/v1/media (specs/sync-protocol-v0.1.md §9). */

@Serializable
data class WireMediaSessionRequest(
    val mediaId: String,
    val submissionId: String,
    val deviceId: String,
    val opId: String? = null,
    val fieldPath: String? = null,
    val mimeType: String,
    val sizeBytes: Long,
    val chunkCount: Int,
    val encrypted: Boolean,
    val contentKeyId: String? = null,
    /**
     * The media key wrapped once per active project key (envelope §6, §4.4).
     * Same shape as an operation content key's wraps, because it is the same
     * construction — only the key it wraps differs.
     */
    val wraps: List<WireWrappedKey> = emptyList(),
)

@Serializable
data class WireMediaSessionResponse(
    val uploadId: String,
    val mediaId: String,
    val chunkSize: Int,
    val chunkCount: Int,
    /**
     * The indexes the server already holds. This is the whole of resumption:
     * the client skips exactly these and sends the rest.
     */
    val receivedChunks: List<Int> = emptyList(),
    val status: String,
    val expiresAt: String? = null,
)

@Serializable
data class WireMediaChunkResponse(
    val mediaId: String,
    val chunkIndex: Int,
    val sizeBytes: Long,
    val receivedChunks: Int,
    val chunkCount: Int,
)

@Serializable
data class WireMediaCompleteRequest(val ciphertextHash: String)

@Serializable
data class WireMediaCompleteResponse(
    val mediaId: String,
    /** The SERVER's hash over what it stored, not an echo of ours. */
    val hash: String,
    val sizeBytes: Long,
    val chunkCount: Int,
    val status: String,
)

@Serializable
data class WireMediaPolicy(
    val imageMaxDimension: Int,
    val imageQuality: Int,
    val gpsMaxAccuracyM: Int,
)

@Serializable
data class WireMediaPolicyResponse(
    val projectId: String,
    val chunkSize: Int,
    val policy: WireMediaPolicy,
)

/** The `{"detail": {"reason", "message"}}` body a media refusal carries. */
@Serializable
data class WireMediaErrorDetail(val reason: String? = null, val message: String? = null)

@Serializable
data class WireMediaErrorBody(val detail: WireMediaErrorDetail? = null)
