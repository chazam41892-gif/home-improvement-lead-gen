package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import com.leadgenpro.android.ui.components.LeadCard
import com.leadgenpro.android.ui.navigation.Screen
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeadsScreen(navController: NavController) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var leads by remember { mutableStateOf<List<Lead>>(emptyList()) }
    var filteredLeads by remember { mutableStateOf<List<Lead>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var minScoreFilter by remember { mutableFloatStateOf(0f) }
    var selectedIndustry by remember { mutableStateOf<String?>(null) }
    var industries by remember { mutableStateOf<List<String>>(emptyList()) }

    fun loadLeads() {
        scope.launch {
            loading = true
            error = null
            try {
                val response = ApiClient.getApiService(context).getLeads()
                if (response.isSuccessful) {
                    leads = response.body()?.leads ?: emptyList()
                    industries = leads.map { it.industry }.distinct().filter { it.isNotBlank() }
                    applyFilters()
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

    fun applyFilters() {
        filteredLeads = leads.filter { lead ->
            (lead.score >= minScoreFilter) &&
                    (selectedIndustry == null || lead.industry == selectedIndustry)
        }
    }

    LaunchedEffect(Unit) {
        loadLeads()
    }

    LaunchedEffect(minScoreFilter, selectedIndustry, leads) {
        applyFilters()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Leads", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Bg,
                    titleContentColor = Text
                )
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
        ) {
            if (loading) {
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Accent)
                }
            } else if (error != null) {
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(text = error ?: "", color = Red)
                        Spacer(modifier = Modifier.height(16.dp))
                        Button(onClick = { loadLeads() }) {
                            Text("Retry")
                        }
                    }
                }
            } else {
                Column(modifier = Modifier.padding(horizontal = 16.dp)) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(
                            text = "${filteredLeads.size} leads",
                            style = MaterialTheme.typography.titleMedium,
                            color = Text2
                        )
                    }

                    Spacer(modifier = Modifier.height(8.dp))

                    Text(
                        text = "Min Score: ${minScoreFilter.toInt()}",
                        style = MaterialTheme.typography.labelMedium,
                        color = Text3
                    )
                    Slider(
                        value = minScoreFilter,
                        onValueChange = { minScoreFilter = it },
                        valueRange = 0f..100f,
                        colors = SliderDefaults.colors(
                            thumbColor = Accent,
                            activeTrackColor = Accent
                        )
                    )

                    if (industries.isNotEmpty()) {
                        Row(
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            FilterChip(
                                selected = selectedIndustry == null,
                                onClick = { selectedIndustry = null },
                                label = { Text("All") },
                                colors = FilterChipDefaults.filterChipColors(
                                    selectedContainerColor = Accent.copy(alpha = 0.2f),
                                    selectedLabelColor = Accent
                                )
                            )
                            industries.take(8).forEach { ind ->
                                FilterChip(
                                    selected = selectedIndustry == ind,
                                    onClick = { selectedIndustry = if (selectedIndustry == ind) null else ind },
                                    label = { Text(ind, maxLines = 1) },
                                    colors = FilterChipDefaults.filterChipColors(
                                        selectedContainerColor = Accent.copy(alpha = 0.2f),
                                        selectedLabelColor = Accent
                                    )
                                )
                            }
                        }
                    }

                    Spacer(modifier = Modifier.height(8.dp))
                }

                if (filteredLeads.isEmpty()) {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = "No leads yet",
                                style = MaterialTheme.typography.titleMedium,
                                color = Text2
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "Run a search first",
                                style = MaterialTheme.typography.bodyMedium,
                                color = Text3
                            )
                        }
                    }
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        items(filteredLeads) { lead ->
                            LeadCard(lead = lead) {
                                navController.navigate(Screen.LeadDetail.createRoute(lead.id))
                            }
                        }
                    }
                }
            }
        }
    }
}
