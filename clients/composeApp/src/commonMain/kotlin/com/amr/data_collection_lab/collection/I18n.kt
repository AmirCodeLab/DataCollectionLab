package com.amr.data_collection_lab.collection

/**
 * Form-language string handling. The form's language is chosen inside the app
 * (a field team shares devices across languages), so these cannot come from the
 * platform locale/resource system — they follow the selected form language.
 */

val RTL_LANGUAGES = setOf("ar", "he", "fa", "ur")

fun isRtl(language: String): Boolean = language.substringBefore("-") in RTL_LANGUAGES

/** Resolves an i18n string map: selected language, then any value, then null. */
fun Map<String, String>?.resolve(language: String): String? =
    this?.get(language) ?: this?.values?.firstOrNull()

/** The handful of fixed UI strings, per supported form language. */
object UiStrings {
    private fun ar(language: String) = language.substringBefore("-") == "ar"

    fun requiredAnswer(l: String) = if (ar(l)) "هذه الإجابة مطلوبة" else "This answer is required"
    fun invalidAnswer(l: String) = if (ar(l)) "إجابة غير صالحة" else "Invalid answer"
    fun notANumber(l: String) = if (ar(l)) "أدخل رقمًا صالحًا" else "Enter a valid number"
    fun pickDate(l: String) = if (ar(l)) "اختر التاريخ" else "Pick a date"
    fun clear(l: String) = if (ar(l)) "مسح" else "Clear"
    fun back(l: String) = if (ar(l)) "رجوع" else "Back"
    fun ok(l: String) = if (ar(l)) "حسنًا" else "OK"
    fun cancel(l: String) = if (ar(l)) "إلغاء" else "Cancel"
    fun next(l: String) = if (ar(l)) "التالي" else "Next"
    fun previous(l: String) = if (ar(l)) "السابق" else "Previous"
    fun finalize(l: String) = if (ar(l)) "إنهاء الاستمارة" else "Finalize"
    fun finalized(l: String) = if (ar(l)) "منتهية" else "Finalized"
    fun invalidRemaining(l: String, n: Int) =
        if (ar(l)) "لا يمكن الإنهاء: $n إجابة تحتاج إلى مراجعة"
        else "Cannot finalize: $n answer(s) need attention"

    // -- media capture --------------------------------------------------

    fun takePhoto(l: String) = if (ar(l)) "التقاط صورة" else "Take photo"
    fun retakePhoto(l: String) = if (ar(l)) "إعادة الالتقاط" else "Retake"
    fun chooseFromGallery(l: String) = if (ar(l)) "اختر من المعرض" else "Gallery"
    fun remove(l: String) = if (ar(l)) "إزالة" else "Remove"
    fun saveSignature(l: String) = if (ar(l)) "حفظ التوقيع" else "Save signature"
    fun shutter(l: String) = if (ar(l)) "التقاط" else "Capture"

    fun capturePosition(l: String) = if (ar(l)) "تحديد الموقع" else "Capture position"
    fun recapturePosition(l: String) = if (ar(l)) "إعادة التحديد" else "Capture again"
    fun findingPosition(l: String) = if (ar(l)) "جارٍ تحديد الموقع…" else "Finding position…"

    /** Good enough for the project's threshold. */
    fun accuracyOk(l: String, m: Int) =
        if (ar(l)) "الدقة: $m متر" else "Accuracy: ${m} m"

    /**
     * Not good enough — and the numbers are the message.
     *
     * "Location unavailable" would be a lie: the phone has a position, it is
     * simply a bad one, and the enumerator can fix that by walking outside. So
     * the text says what was measured, what is needed, and what to do.
     */
    fun accuracyTooPoor(l: String, m: Int, required: Int) =
        if (ar(l)) "الدقة $m متر — المطلوب $required متر أو أقل. اخرج إلى مكان مفتوح."
        else "Accuracy ${m} m — the project needs ${required} m or better. Step outside."

    fun accuracyUnknown(l: String, required: Int) =
        if (ar(l)) "الجهاز لم يُبلّغ عن الدقة — المطلوب $required متر أو أقل."
        else "The device did not report an accuracy — the project needs ${required} m or better."

    fun positionTimedOut(l: String) =
        if (ar(l)) "لم يتم العثور على الموقع بعد. حاول في مكان مفتوح."
        else "No position yet. Try again with a clear view of the sky."

    fun mediaStaged(l: String) = if (ar(l)) "محفوظة على الجهاز" else "Saved on this device"
    fun mediaUploaded(l: String) = if (ar(l)) "تم الرفع" else "Uploaded"
    fun mediaUploadFailed(l: String, reason: String) =
        if (ar(l)) "لم يتم الرفع: $reason" else "Not uploaded yet: $reason"

    fun locationPermissionRefused(l: String) =
        if (ar(l)) "تم رفض إذن الموقع. يمكنك منحه من الإعدادات."
        else "Location permission was refused. Grant it in Settings to record a position."

    fun captureUnavailable(l: String) =
        if (ar(l)) "لا تتوفر الكاميرا على هذا الجهاز"
        else "This device cannot take photographs"
}
