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
}
