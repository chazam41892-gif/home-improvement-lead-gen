package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.Lead
import com.leadgenpro.android.api.MultiSearchRequest
import com.leadgenpro.android.api.MultiSearchResponse
import com.leadgenpro.android.api.SearchRequest
import com.leadgenpro.android.api.SearchResponse
import com.leadgenpro.android.ui.components.LeadCard
import com.leadgenpro.android.ui.navigation.Screen
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(navController: NavController) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var query by remember { mutableStateOf("") }
    var resultCount by remember { mutableIntStateOf(25) }
    var minScore by remember { mutableDoubleStateOf(0.0) }
    var provider by remember { mutableStateOf("exa") }
    var multiSource by remember { mutableStateOf(false) }
    var results by remember { mutableStateOf<List<Lead>>(emptyList()) }
    var searchHistory by remember { mutableStateOf<List<String>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var totalFound by remember { mutableIntStateOf(0) }

    fun performSearch() {
        if (query.isBlank()) return
        scope.launch {
            loading = true
            error = null
            try {
                searchHistory = (listOf(query) + searchHistory).take(10)
                if (multiSource) {
                    val req = MultiSearchRequest(
                        queries = listOf(query),
                        result_count = resultCount,
                        min_score = minScore
                    )
                    val response = ApiClient.getApiService(context).searchMulti(req)
                    if (response.isSuccessful) {
                        val body = response.body()
                        results = body?.results ?: emptyList()
                        totalFound = body?.total_found ?: 0
                    } else {
                        error = "Error: ${response.code()}"
                    }
                } else {
                    val req = SearchRequest(
                        query = query,
                        result_count = resultCount,
                        min_score = minScore,
                        provider = provider
                    )
                    val response = ApiClient.getApiService(context).searchLeads(req)
                    if (response.isSuccessful) {
                        val body = response.body()
                        results = body?.results ?: emptyList()
                        totalFound = body?.total_found ?: 0
                    } else {
                        error = "Error: ${response.code()}"
                    }
                }
            } catch (e: Exception) {
                error = e.message ?: "Connection failed"
            } finally {
                loading = false
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Search", fontWeight = FontWeight.Bold) },
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
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text("Natural language query") },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedBorderColor = Accent,
                        unfocusedBorderColor = Bg3,
                        focusedLabelColor = Accent,
                        cursorColor = Accent
                    ),
                    singleLine = true
                )
            }

            item {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Results: $resultCount", color = Text2, style = MaterialTheme.typography.labelMedium)
                        Slider(
                            value = resultCount.toFloat(),
                            onValueChange = { resultCount = it.toInt() },
                            valueRange = 10f..100f,
                            steps = 4,
                            colors = SliderDefaults.colors(
                                thumbColor = Accent,
                                activeTrackColor = Accent
                            )
                        )
                    }
                }
            }

            item {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Min Score: ${String.format("%.0f", minScore)}", color = Text2, style = MaterialTheme.typography.labelMedium)
                        Slider(
                            value = minScore.toFloat(),
                            onValueChange = { minScore = it.toDouble() },
                            valueRange = 0f..100f,
                            colors = SliderDefaults.colors(
                                thumbColor = Accent,
                                activeTrackColor = Accent
                            )
                        )
                    }
                }
            }

            item {
                Row(
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    providerOptions.forEach { p ->
                        FilterChip(
                            selected = provider == p.value && !multiSource,
                            onClick = {
                                provider = p.value
                                multiSource = false
                            },
                            label = { Text(p.label) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = Accent.copy(alpha = 0.2f),
                                selectedLabelColor = Accent
                            )
                        )
                    }
                    Spacer(modifier = Modifier.width(8.dp))
                    FilterChip(
                        selected = multiSource,
                        onClick = { multiSource = !multiSource },
                        label = { Text("Multi") },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = Accent.copy(alpha = 0.2f),
                            selectedLabelColor = Accent
                        )
                    )
                }
            }

            item {
                Button(
                    onClick = { performSearch() },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Accent),
                    enabled = query.isNotBlank() && !loading
                ) {
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = OnPrimary,
                            strokeWidth = 2.dp
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Searching...")
                    } else {
                        Icon(Icons.Default.Search, contentDescription = null)
                        Spacer(modifier = Modifier.width(8.dp))
                        Text("Search")
                    }
                }
            }

            if (error != null) {
                item {
                    Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = RedBg)
                    ) {
                        Text(
                            text = error ?: "",
                            modifier = Modifier.padding(16.dp),
                            color = Red
                        )
                    }
                }
            }

            if (results.isNotEmpty()) {
                item {
                    Text(
                        text = "Results ($totalFound found)",
                        style = MaterialTheme.typography.titleMedium,
                        color = Text
                    )
                }

                items(results) { lead ->
                    LeadCard(lead = lead) {
                        navController.navigate(Screen.LeadDetail.createRoute(lead.id))
                    }
                }
            }

            if (searchHistory.isNotEmpty() && results.isEmpty()) {
                item {
                    Text(
                        text = "Search History",
                        style = MaterialTheme.typography.titleMedium,
                        color = Text,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }

                items(searchHistory) { h ->
                    Card(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable {
                                query = h
                                performSearch()
                            },
                        shape = RoundedCornerShape(8.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Text(
                            text = h,
                            modifier = Modifier.padding(12.dp),
                            color = Text2
                        )
                    }
                }
            }
        }
    }
}

private val providerOptions = listOf(
    "exa" to "Exa",
    "perplexity" to "Perplexity"
).map { ProviderOption(it.first, it.second) }

private data class ProviderOption(val value: String, val label: String)
