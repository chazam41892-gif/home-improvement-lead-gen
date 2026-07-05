package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.api.AdCopyRequest
import com.leadgenpro.android.api.PixelRequest
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdsScreen() {
    var tabIndex by remember { mutableIntStateOf(0) }
    val tabs = listOf("Ad Copy", "Keywords", "Pixels")

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Ads", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg, titleContentColor = Text)
            )
        }
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            TabRow(
                selectedTabIndex = tabIndex,
                containerColor = Bg,
                contentColor = Accent
            ) {
                tabs.forEachIndexed { index, title ->
                    Tab(
                        selected = tabIndex == index,
                        onClick = { tabIndex = index },
                        text = { Text(title) }
                    )
                }
            }

            when (tabIndex) {
                0 -> AdCopyTab()
                1 -> KeywordsTab()
                2 -> PixelsTab()
            }
        }
    }
}

@Composable
private fun AdCopyTab() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var industry by remember { mutableStateOf("") }
    var location by remember { mutableStateOf("") }
    var platform by remember { mutableStateOf("Google") }
    var usp by remember { mutableStateOf("") }
    var count by remember { mutableIntStateOf(3) }
    var copies by remember { mutableStateOf<com.leadgenpro.android.api.AdCopyResponse?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun generate() {
        if (industry.isBlank() || location.isBlank()) return
        scope.launch {
            loading = true
            error = null
            try {
                val req = AdCopyRequest(industry = industry, location = location, platform = platform, usp = usp, count = count)
                val response = ApiClient.getApiService(context).generateAdCopy(req)
                if (response.isSuccessful) {
                    copies = response.body()
                } else {
                    error = "Error: ${response.code()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Connection failed"
            } finally {
                loading = false
            }
        }
    }

    LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            OutlinedTextField(value = industry, onValueChange = { industry = it }, label = { Text("Industry") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
        }
        item {
            OutlinedTextField(value = location, onValueChange = { location = it }, label = { Text("Location") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
        }
        item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf("Google", "Facebook", "LSA").forEach { p ->
                    FilterChip(selected = platform == p, onClick = { platform = p }, label = { Text(p) })
                }
            }
        }
        item {
            OutlinedTextField(value = usp, onValueChange = { usp = it }, label = { Text("USP (optional)") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
        }
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Count: $count", color = Text2, modifier = Modifier.weight(1f))
            }
            Slider(value = count.toFloat(), onValueChange = { count = it.toInt() }, valueRange = 1f..10f, steps = 8)
        }
        item {
            Button(onClick = { generate() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), colors = ButtonDefaults.buttonColors(containerColor = Accent), enabled = industry.isNotBlank() && location.isNotBlank() && !loading) {
                if (loading) CircularProgressIndicator(modifier = Modifier.size(18.dp), color = OnPrimary, strokeWidth = 2.dp)
                else Text("Generate")
            }
        }

        if (error != null) {
            item { Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = RedBg)) { Text(error ?: "", modifier = Modifier.padding(16.dp), color = Red) } }
        }

        copies?.copies?.let { ads ->
            items(ads) { ad ->
                Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(ad.headline, style = MaterialTheme.typography.titleMedium, color = Text, fontWeight = FontWeight.Bold)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(ad.description, style = MaterialTheme.typography.bodyMedium, color = Text2)
                        Spacer(modifier = Modifier.height(4.dp))
                        Text("CTA: ${ad.cta}", style = MaterialTheme.typography.labelMedium, color = Accent)
                    }
                }
            }
        }
    }
}

@Composable
private fun KeywordsTab() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var industry by remember { mutableStateOf("") }
    var location by remember { mutableStateOf("") }
    var keywords by remember { mutableStateOf<com.leadgenpro.android.api.Keywords?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun generate() {
        if (industry.isBlank()) return
        scope.launch {
            loading = true
            error = null
            try {
                val body = mapOf("industry" to industry, "location" to location)
                val response = ApiClient.getApiService(context).generateKeywords(body)
                if (response.isSuccessful) {
                    keywords = response.body()?.keywords
                } else {
                    error = "Error: ${response.code()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Connection failed"
            } finally {
                loading = false
            }
        }
    }

    LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { OutlinedTextField(value = industry, onValueChange = { industry = it }, label = { Text("Industry") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true) }
        item { OutlinedTextField(value = location, onValueChange = { location = it }, label = { Text("Location") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true) }
        item {
            Button(onClick = { generate() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), colors = ButtonDefaults.buttonColors(containerColor = Accent), enabled = industry.isNotBlank() && !loading) {
                if (loading) CircularProgressIndicator(modifier = Modifier.size(18.dp), color = OnPrimary, strokeWidth = 2.dp)
                else Text("Generate")
            }
        }

        if (error != null) {
            item { Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = RedBg)) { Text(error ?: "", modifier = Modifier.padding(16.dp), color = Red) } }
        }

        keywords?.let { kw ->
            item { Text("Broad (${kw.broad.size})", style = MaterialTheme.typography.titleSmall, color = Text) }
            items(kw.broad) { k -> KeywordChip(k) }
            item { Text("Phrase (${kw.phrase.size})", style = MaterialTheme.typography.titleSmall, color = Text) }
            items(kw.phrase) { k -> KeywordChip(k) }
            item { Text("Exact (${kw.exactMatch.size})", style = MaterialTheme.typography.titleSmall, color = Text) }
            items(kw.exactMatch) { k -> KeywordChip(k) }
            item { Text("Negative (${kw.negative.size})", style = MaterialTheme.typography.titleSmall, color = Text) }
            items(kw.negative) { k -> KeywordChip(k) }
        }
    }
}

@Composable
private fun KeywordChip(text: String) {
    Card(shape = RoundedCornerShape(6.dp), colors = CardDefaults.cardColors(containerColor = Bg3), modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(12.dp), color = Text2, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun PixelsTab() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var pixelType by remember { mutableStateOf("Google Ads") }
    var trackingId by remember { mutableStateOf("") }
    var pixelResult by remember { mutableStateOf<com.leadgenpro.android.api.PixelResponse?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun generate() {
        if (trackingId.isBlank()) return
        scope.launch {
            loading = true
            error = null
            try {
                val req = PixelRequest(type = pixelType, trackingId = trackingId)
                val response = ApiClient.getApiService(context).generatePixel(req)
                if (response.isSuccessful) {
                    pixelResult = response.body()
                } else {
                    error = "Error: ${response.code()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Connection failed"
            } finally {
                loading = false
            }
        }
    }

    LazyColumn(modifier = Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            var expanded by remember { mutableStateOf(false) }
            ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
                OutlinedTextField(
                    value = pixelType,
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Type") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expanded) },
                    modifier = Modifier.menuAnchor().fillMaxWidth(),
                    shape = RoundedCornerShape(8.dp)
                )
                ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                    listOf("Google Ads", "Facebook Pixel", "LinkedIn").forEach { opt ->
                        DropdownMenuItem(text = { Text(opt) }, onClick = { pixelType = opt; expanded = false })
                    }
                }
            }
        }
        item {
            OutlinedTextField(value = trackingId, onValueChange = { trackingId = it }, label = { Text("Tracking ID") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
        }
        item {
            Button(onClick = { generate() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), colors = ButtonDefaults.buttonColors(containerColor = Accent), enabled = trackingId.isNotBlank() && !loading) {
                if (loading) CircularProgressIndicator(modifier = Modifier.size(18.dp), color = OnPrimary, strokeWidth = 2.dp)
                else Text("Generate Pixel")
            }
        }

        if (error != null) {
            item { Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = RedBg)) { Text(error ?: "", modifier = Modifier.padding(16.dp), color = Red) } }
        }

        pixelResult?.let { result ->
            item {
                Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                            Text("Pixel HTML", style = MaterialTheme.typography.titleSmall, color = Text)
                            IconButton(onClick = {
                                val clipboard = context.getSystemService(android.content.Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                                val clip = android.content.ClipData.newPlainText("pixel", result.html)
                                clipboard.setPrimaryClip(clip)
                            }) {
                                Icon(Icons.Default.ContentCopy, contentDescription = "Copy", tint = Accent)
                            }
                        }
                        Spacer(modifier = Modifier.height(8.dp))
                        Surface(shape = RoundedCornerShape(8.dp), color = Bg) {
                            Text(
                                text = result.html,
                                modifier = Modifier
                                    .padding(12.dp)
                                    .horizontalScroll(rememberScrollState()),
                                style = MaterialTheme.typography.bodySmall,
                                color = Text2
                            )
                        }
                    }
                }
            }
        }
    }
}
