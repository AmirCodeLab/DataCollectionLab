package com.amr.data_collection_lab.collection

import com.dcp.form.CompiledForm
import com.dcp.form.FormIr
import datacollectionlab.clients.composeapp.generated.resources.Res
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/**
 * Loads and compiles the bundled form. One form for now; becomes the local
 * form-version store once pull sync exists.
 */
class FormCatalog {
    private val mutex = Mutex()
    private var cached: CompiledForm? = null

    suspend fun compiledForm(): CompiledForm = mutex.withLock {
        cached ?: withContext(Dispatchers.Default) {
            val json = Res.readBytes("files/household_survey.json").decodeToString()
            CompiledForm(FormIr.parse(json))
        }.also { cached = it }
    }
}
