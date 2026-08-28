package com.amr.data_collection_lab

interface Platform {
    val name: String
}

expect fun getPlatform(): Platform