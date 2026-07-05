package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavController
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.BusinessConfig
import com.leadgenpro.android.api.CaptureStats
import com.leadgenpro.android.api.SchedulerStats
import com.leadgenpro.android.api.StatsResponse
import com.leadgenpro.android.ui.components.StatCard
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(navController: NavController) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var stats by remember { mutableStateOf<StatsResponse?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    fun loadStats() {
        scope.launch {
            loading = true
            error = null
            try {
                val response = ApiClient.getApiService(context).getStats()
                if (response.isSuccessful) {
                    stats = response.body()
                } else {
                    error = "Error: ${response.code()} ${response.message()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Unknown error"
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) {
        loadStats()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Lead Gen Pro", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = { loadStats() }) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Bg,
                    titleContentColor = Text
                )
            )
        }
    ) { padding ->
        if (loading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator(color = Accent)
            }
        } else if (error != null) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = error ?: "Error loading data",
                        color = Red,
                        style = MaterialTheme.typography.bodyLarge
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = { loadStats() }) {
                        Text("Retry")
                    }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    Text(
                        text = "Overview",
                        style = MaterialTheme.typography.titleLarge,
                        color = Text
                    )
                }

                item {
                    LazyVerticalGrid(
                        columns = GridCells.Fixed(3),
                        modifier = Modifier.height(140.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        items(
                            listOf(
                                Triple("Total Leads", "${stats?.total_leads ?: 0}", Accent),
                                Triple("Avg Score", String.format("%.1f", stats?.avg_score ?: 0.0), Accent2),
                                Triple("Searches", "${stats?.searches_run ?: 0}", Green)
                            )
                        ) { (label, value, color) ->
                            StatCard(
                                label = label,
                                value = value,
                                color = color
                            )
                        }
                    }
                }

                item {
                    Text(
                        text = "Scheduler",
                        style = MaterialTheme.typography.titleLarge,
                        color = Text,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }

                item {
                    stats?.scheduler?.let { sched ->
                        SchedulerStatsSection(sched)
                    } ?: Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Text(
                            text = "No scheduler data",
                            modifier = Modifier.padding(16.dp),
                            color = Text2,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }

                item {
                    Text(
                        text = "Capture",
                        style = MaterialTheme.typography.titleLarge,
                        color = Text,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }

                item {
                    stats?.capture?.let { cap ->
                        CaptureStatsSection(cap)
                    } ?: Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Text(
                            text = "No capture data",
                            modifier = Modifier.padding(16.dp),
                            color = Text2,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }

                item {
                    Text(
                        text = "Business Metrics",
                        style = MaterialTheme.typography.titleLarge,
                        color = Text,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }

                item {
                    stats?.business_config?.let { config ->
                        BusinessMetricsSection(config)
                    } ?: Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Text(
                            text = "Configure business settings",
                            modifier = Modifier.padding(16.dp),
                            color = Text2,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                }

                item { Spacer(modifier = Modifier.height(32.dp)) }
            }
        }
    }
}

@Composable
private fun SchedulerStatsSection(sched: SchedulerStats) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        modifier = Modifier.height(140.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(
            listOf(
                Triple("Schedules", "${sched.total_schedules}", Accent),
                Triple("Enabled", "${sched.enabled}", Green),
                Triple("Total Runs", "${sched.total_runs}", Accent2)
            )
        ) { (label, value, color) ->
            StatCard(label = label, value = value, color = color)
        }
    }
}

@Composable
private fun CaptureStatsSection(cap: CaptureStats) {
    LazyVerticalGrid(
        columns = GridCells.Fixed(3),
        modifier = Modifier.height(140.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(
            listOf(
                Triple("Submissions", "${cap.total_submissions}", Accent),
                Triple("Today", "${cap.today}", Green),
                Triple("Converted", "${cap.converted}", Accent2)
            )
        ) { (label, value, color) ->
            StatCard(label = label, value = value, color = color)
        }
    }
}

@Composable
private fun BusinessMetricsSection(config: BusinessConfig) {
    Card(
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Bg2),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                MetricItem("Profit/Job", "$${String.format("%.0f", config.profit_per_job)}", Green)
                MetricItem("CAC", "$${String.format("%.0f", config.cac)}", Yellow)
                MetricItem("Max CPC", "$${String.format("%.2f", config.max_cpc)}", Accent2)
                MetricItem("B/E Leads", "${config.break_even_leads}", Red)
            }
        }
    }
}

@Composable
private fun MetricItem(label: String, value: String, color: androidx.compose.ui.graphics.Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = value,
            fontWeight = FontWeight.Bold,
            fontSize = MaterialTheme.typography.titleMedium.fontSize,
            color = color
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelSmall,
            color = Text3
        )
    }
}
