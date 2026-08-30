package com.amr.data_collection_lab.collection

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.CanvasDrawScope
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp

/**
 * The three media answer widgets: a photograph, a signature and a position.
 *
 * All three share one rule, and it is the reason they are grouped here: **the
 * widget never decides whether an answer is good enough.** Compression limits
 * and the GPS accuracy threshold come from the project and are enforced in
 * `shared/core`, so Android, iOS and desktop cannot quietly disagree about what
 * they accept. What lives here is what the enumerator sees and touches.
 */

// ---------------------------------------------------------------------------
// Image
// ---------------------------------------------------------------------------

@Composable
fun ImageAnswer(
    question: QuestionUi,
    language: String,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    val media = question.media
    val openGallery = rememberGalleryPicker { bytes ->
        if (bytes != null) onAction(CollectionAction.OnImageCaptured(question.path, bytes))
    }

    Column(modifier = Modifier.fillMaxWidth()) {
        if (media != null) {
            // What is on screen is what is staged: name, size and — once the
            // upload has run — whether the server has it. An enumerator who
            // cannot tell a photograph that has synced from one that has not is
            // an enumerator who hands the device back too early.
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .height(96.dp)
                    .background(MaterialTheme.colorScheme.surfaceVariant)
                    .padding(12.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                Column {
                    Text(media.filename, style = MaterialTheme.typography.bodyMedium)
                    Text(
                        media.status,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (isCaptureSupported()) {
                Button(
                    onClick = { onAction(CollectionAction.OnOpenCamera(question.path)) },
                    enabled = enabled,
                ) {
                    Text(if (media == null) UiStrings.takePhoto(language) else UiStrings.retakePhoto(language))
                }
            }
            OutlinedButton(onClick = openGallery, enabled = enabled) {
                Text(UiStrings.chooseFromGallery(language))
            }
            if (media != null) {
                TextButton(
                    onClick = { onAction(CollectionAction.OnClearMedia(question.path)) },
                    enabled = enabled,
                ) {
                    Text(UiStrings.remove(language))
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Signature
// ---------------------------------------------------------------------------

/** One continuous stroke, in canvas coordinates. */
private class SignatureStroke(val points: MutableList<Offset> = mutableListOf())

@Composable
fun SignatureAnswer(
    question: QuestionUi,
    language: String,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    var strokes by remember(question.path) { mutableStateOf(listOf<SignatureStroke>()) }
    var current by remember(question.path) { mutableStateOf<SignatureStroke?>(null) }
    var canvasSize by remember(question.path) { mutableStateOf(IntSize.Zero) }
    // Bumped on every point so the Canvas recomposes: the stroke list itself is
    // mutated in place, and Compose cannot see inside it.
    var revision by remember(question.path) { mutableStateOf(0) }

    Column(modifier = Modifier.fillMaxWidth()) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                // Wider than tall, like the paper line a signature is written
                // on. A square box invites people to draw a picture in it.
                .aspectRatio(2.5f)
                .background(Color.White)
                .border(1.dp, MaterialTheme.colorScheme.outline)
                .onSizeChanged { canvasSize = it }
                .pointerInput(enabled, question.path) {
                    if (!enabled) return@pointerInput
                    detectDragGestures(
                        onDragStart = { offset ->
                            current = SignatureStroke(mutableListOf(offset))
                            revision++
                        },
                        onDrag = { change, _ ->
                            current?.points?.add(change.position)
                            revision++
                        },
                        onDragEnd = {
                            current?.let { strokes = strokes + it }
                            current = null
                            revision++
                        },
                    )
                },
        ) {
            Canvas(modifier = Modifier.fillMaxWidth().aspectRatio(2.5f)) {
                @Suppress("UNUSED_EXPRESSION") revision
                drawSignature(strokes + listOfNotNull(current))
            }
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                enabled = enabled && strokes.isNotEmpty() && canvasSize != IntSize.Zero,
                onClick = {
                    // Rasterised here, in common code, and encoded to PNG by the
                    // platform — there is no PNG encoder in common Kotlin, and a
                    // hand-rolled one would mean hand-rolling DEFLATE.
                    val pixels = rasterise(strokes, canvasSize)
                    onAction(
                        CollectionAction.OnSignatureDrawn(
                            question.path, pixels, canvasSize.width, canvasSize.height,
                        )
                    )
                },
            ) { Text(UiStrings.saveSignature(language)) }

            OutlinedButton(
                enabled = enabled && (strokes.isNotEmpty() || question.media != null),
                onClick = {
                    strokes = emptyList()
                    current = null
                    revision++
                    if (question.media != null) {
                        onAction(CollectionAction.OnClearMedia(question.path))
                    }
                },
            ) { Text(UiStrings.clear(language)) }
        }

        question.media?.let {
            Text(
                it.status,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

private fun DrawScope.drawSignature(strokes: List<SignatureStroke>) {
    for (stroke in strokes) {
        if (stroke.points.size < 2) continue
        val path = Path().apply {
            moveTo(stroke.points.first().x, stroke.points.first().y)
            stroke.points.drop(1).forEach { lineTo(it.x, it.y) }
        }
        drawPath(
            path = path,
            color = Color.Black,
            style = Stroke(width = 3f, cap = StrokeCap.Round, join = StrokeJoin.Round),
        )
    }
}

/**
 * Draws the strokes into an offscreen bitmap and reads the pixels back as
 * RGBA8888 — all common Compose, so the signature is rasterised identically on
 * every platform.
 */
private fun rasterise(strokes: List<SignatureStroke>, size: IntSize): ByteArray {
    val bitmap = ImageBitmap(size.width, size.height)
    CanvasDrawScope().draw(
        density = Density(1f),
        layoutDirection = LayoutDirection.Ltr,
        canvas = androidx.compose.ui.graphics.Canvas(bitmap),
        size = androidx.compose.ui.geometry.Size(size.width.toFloat(), size.height.toFloat()),
    ) {
        // Opaque white, not transparent: a signature on a transparent ground
        // renders as an invisible smudge in every viewer with a dark theme, and
        // this is a document someone may be asked to stand behind.
        drawRect(Color.White)
        drawSignature(strokes)
    }

    val pixels = IntArray(size.width * size.height)
    bitmap.readPixels(pixels)
    val out = ByteArray(pixels.size * 4)
    var i = 0
    for (argb in pixels) {
        out[i] = ((argb shr 16) and 0xFF).toByte()
        out[i + 1] = ((argb shr 8) and 0xFF).toByte()
        out[i + 2] = (argb and 0xFF).toByte()
        out[i + 3] = ((argb shr 24) and 0xFF).toByte()
        i += 4
    }
    return out
}

// ---------------------------------------------------------------------------
// Geopoint
// ---------------------------------------------------------------------------

@Composable
fun GeoPointAnswer(
    question: QuestionUi,
    language: String,
    enabled: Boolean,
    onAction: (CollectionAction) -> Unit,
) {
    val geo = question.geo

    Column(modifier = Modifier.fillMaxWidth()) {
        if (geo != null) {
            Text(geo.coordinates, style = MaterialTheme.typography.bodyLarge)
            Text(
                geo.accuracyText,
                style = MaterialTheme.typography.bodySmall,
                // The refusal is not an error state to be got past — it is the
                // reading being reported honestly. A phone under a tin roof
                // gives a 2 km "fix" with exactly the authority of a good one,
                // and the only defence is showing the number.
                color = if (geo.accepted) MaterialTheme.colorScheme.onSurfaceVariant
                else MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(top = 2.dp),
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Button(
                onClick = { onAction(CollectionAction.OnCaptureLocation(question.path)) },
                enabled = enabled && !question.capturing,
            ) {
                Text(
                    when {
                        question.capturing -> UiStrings.findingPosition(language)
                        geo == null -> UiStrings.capturePosition(language)
                        else -> UiStrings.recapturePosition(language)
                    }
                )
            }
            if (geo != null) {
                TextButton(
                    onClick = { onAction(CollectionAction.OnClearGeoPoint(question.path)) },
                    enabled = enabled,
                ) { Text(UiStrings.remove(language)) }
            }
        }
    }
}
