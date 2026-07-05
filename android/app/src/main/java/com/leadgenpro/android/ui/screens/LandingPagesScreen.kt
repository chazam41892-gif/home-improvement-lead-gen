package com.leadgenpro.android.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.LandingPage
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LandingPagesScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var pages by remember { mutableStateOf<List<LandingPage>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var showForm by remember { mutableStateOf(false) }

    var bizName by remember { mutableStateOf("") }
    var headline by remember { mutableStateOf("") }
    var cta by remember { mutableStateOf("") }
    var pageColor by remember { mutableStateOf("#6366F1") }
    var creating by remember { mutableStateOf(false) }

    fun loadPages() {
        scope.launch {
            loading = true
            error = null
            try {
                val response = ApiClient.getApiService(context).listLandingPages()
                if (response.isSuccessful) {
                    pages = response.body()?.pages ?: emptyList()
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

    fun createPage() {
        if (bizName.isBlank() || headline.isBlank()) return
        scope.launch {
            creating = true
            try {
                val body = mapOf(
                    "business_name" to bizName,
                    "headline" to headline,
                    "cta" to cta,
                    "color" to pageColor
                )
                val response = ApiClient.getApiService(context).createLandingPage(body)
                if (response.isSuccessful) {
                    bizName = ""; headline = ""; cta = ""
                    showForm = false
                    loadPages()
                }
            } catch (_: Exception) { } finally {
                creating = false
            }
        }
    }

    fun deletePage(id: String) {
        scope.launch {
            try {
                ApiClient.getApiService(context).deleteLandingPage(id)
                loadPages()
            } catch (_: Exception) { }
        }
    }

    LaunchedEffect(Unit) { loadPages() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Landing Pages", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = { showForm = !showForm }) {
                        Icon(if (showForm) Icons.Default.Close else Icons.Default.Add, contentDescription = "Toggle form")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Bg,
                    titleContentColor = Text
                )
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                AnimatedVisibility(visible = showForm) {
                    Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("Create Landing Page", style = MaterialTheme.typography.titleMedium, color = Text)
                            Spacer(modifier = Modifier.height(12.dp))

                            OutlinedTextField(
                                value = bizName,
                                onValueChange = { bizName = it },
                                label = { Text("Business Name") },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                singleLine = true
                            )
                            Spacer(modifier = Modifier.height(8.dp))

                            OutlinedTextField(
                                value = headline,
                                onValueChange = { headline = it },
                                label = { Text("Headline") },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                singleLine = true
                            )
                            Spacer(modifier = Modifier.height(8.dp))

                            OutlinedTextField(
                                value = cta,
                                onValueChange = { cta = it },
                                label = { Text("CTA Text") },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                singleLine = true
                            )
                            Spacer(modifier = Modifier.height(12.dp))

                            Button(
                                onClick = { createPage() },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Accent),
                                enabled = bizName.isNotBlank() && headline.isNotBlank() && !creating
                            ) {
                                if (creating) {
                                    CircularProgressIndicator(modifier = Modifier.size(18.dp), color = OnPrimary, strokeWidth = 2.dp)
                                } else {
                                    Text("Generate Page")
                                }
                            }
                        }
                    }
                }
            }

            if (loading) {
                item {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = Accent)
                    }
                }
            } else if (error != null) {
                item {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = RedBg)) {
                        Text(error ?: "", modifier = Modifier.padding(16.dp), color = Red)
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(onClick = { loadPages() }) { Text("Retry") }
                }
            } else if (pages.isEmpty()) {
                item {
                    Box(modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp), contentAlignment = Alignment.Center) {
                        Text("No landing pages yet", color = Text2)
                    }
                }
            } else {
                items(pages) { page ->
                    Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(page.business_name, style = MaterialTheme.typography.titleMedium, color = Text)
                                    Text("ID: ${page.page_id}", style = MaterialTheme.typography.bodySmall, color = Text3)
                                }
                                Row {
                                    IconButton(onClick = {
                                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(page.url))
                                        context.startActivity(intent)
                                    }) {
                                        Icon(Icons.Default.OpenInNew, contentDescription = "Preview", tint = Accent)
                                    }
                                    IconButton(onClick = { deletePage(page.id) }) {
                                        Icon(Icons.Default.Delete, contentDescription = "Delete", tint = Red)
                                    }
                                }
                            }
                            Spacer(modifier = Modifier.height(4.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                                Text("Size: ${page.page_size}", style = MaterialTheme.typography.bodySmall, color = Text3)
                                Text("Headline: ${page.headline}", style = MaterialTheme.typography.bodySmall, color = Text3, maxLines = 1)
                            }
                        }
                    }
                }
            }
        }
    }
}
