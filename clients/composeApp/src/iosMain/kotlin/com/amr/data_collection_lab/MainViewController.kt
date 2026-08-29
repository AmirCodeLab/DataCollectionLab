package com.amr.data_collection_lab

import androidx.compose.ui.window.ComposeUIViewController
import com.dcp.core.sync.DatabaseDriverFactory

fun MainViewController() = ComposeUIViewController { App(DatabaseDriverFactory()) }
