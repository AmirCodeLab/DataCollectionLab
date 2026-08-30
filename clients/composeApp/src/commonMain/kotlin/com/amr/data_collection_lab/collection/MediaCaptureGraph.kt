package com.amr.data_collection_lab.collection

import com.dcp.core.media.GeoCapture
import com.dcp.core.media.ImageCompressor
import com.dcp.core.media.ImageEncoder
import com.dcp.core.media.MediaStaging
import com.dcp.core.media.MediaStore

/**
 * The media pieces a [CollectionViewModel] needs, bundled so its constructor
 * says "media capture, or none" rather than listing five collaborators.
 *
 * Null on a client with no capture — the desktop review app — where the
 * ViewModel renders image, signature and geopoint questions as unavailable
 * rather than as a widget that cannot answer them.
 */
class MediaCaptureGraph(
    val store: MediaStore,
    val staging: MediaStaging,
    val compressor: ImageCompressor,
    val encoder: ImageEncoder,
    val geo: GeoCapture,
)
