package com.leadgenpro.android.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.Lead
import com.leadgenpro.android.api.Schedule
import com.leadgenpro.android.ui.components.LeadCard
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SchedulesScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var schedules by remember { mutableStateOf<List<Schedule>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var showForm by remember { mutableStateOf(false) }
    var expandedResults by remember { mutableStateOf<Set<String>>(emptySet()) }

    var schedName by remember { mutableStateOf("") }
    var schedQuery by remember { mutableStateOf("") }
    var schedProvider by remember { mutableStateOf("exa") }
    var schedCount by remember { mutableIntStateOf(25) }
    var schedInterval by remember { mutableStateOf("daily") }
    var creating by remember { mutableStateOf(false) }

    fun loadSchedules() {
        scope.launch {
            loading = true
            error = null
            try {
                val response = ApiClient.getApiService(context).listSchedules()
                if (response.isSuccessful) {
                    schedules = response.body()?.schedules ?: emptyList()
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

    fun createSchedule() {
        if (schedName.isBlank() || schedQuery.isBlank()) return
        scope.launch {
            creating = true
            try {
                val body = mapOf<String, Any>(
                    "name" to schedName,
                    "query" to schedQuery,
                    "provider" to schedProvider,
                    "interval" to schedInterval,
                    "result_count" to schedCount
                )
                val response = ApiClient.getApiService(context).createSchedule(body)
                if (response.isSuccessful) {
                    schedName = ""; schedQuery = ""
                    showForm = false
                    loadSchedules()
                }
            } catch (_: Exception) { } finally {
                creating = false
            }
        }
    }

    fun toggleSchedule(schedule: Schedule) {
        scope.launch {
            try {
                val body = mapOf<String, Any>("enabled" to !schedule.enabled)
                ApiClient.getApiService(context).updateSchedule(schedule.id, body)
                loadSchedules()
            } catch (_: Exception) { }
        }
    }

    fun deleteSchedule(id: String) {
        scope.launch {
            try {
                ApiClient.getApiService(context).deleteSchedule(id)
                loadSchedules()
            } catch (_: Exception) { }
        }
    }

    LaunchedEffect(Unit) { loadSchedules() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Schedules", fontWeight = FontWeight.Bold) },
                actions = {
                    IconButton(onClick = { showForm = !showForm }) {
                        Icon(if (showForm) Icons.Default.Close else Icons.Default.Add, contentDescription = "Toggle form")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg, titleContentColor = Text)
            )
        }
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            item {
                AnimatedVisibility(visible = showForm) {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("Create Schedule", style = MaterialTheme.typography.titleMedium, color = Text)
                            Spacer(modifier = Modifier.height(12.dp))
                            OutlinedTextField(value = schedName, onValueChange = { schedName = it }, label = { Text("Name") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
                            Spacer(modifier = Modifier.height(8.dp))
                            OutlinedTextField(value = schedQuery, onValueChange = { schedQuery = it }, label = { Text("Query") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                FilterChip(selected = schedProvider == "exa", onClick = { schedProvider = "exa" }, label = { Text("Exa") })
                                FilterChip(selected = schedProvider == "perplexity", onClick = { schedProvider = "perplexity" }, label = { Text("Perplexity") })
                            }
                            Spacer(modifier = Modifier.height(8.dp))
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text("Count: $schedCount", color = Text2, modifier = Modifier.weight(1f))
                            }
                            Slider(value = schedCount.toFloat(), onValueChange = { schedCount = it.toInt() }, valueRange = 10f..100f, steps = 4)
                            Spacer(modifier = Modifier.height(8.dp))

                            var expandedInterval by remember { mutableStateOf(false) }
                            ExposedDropdownMenuBox(expanded = expandedInterval, onExpandedChange = { expandedInterval = it }) {
                                OutlinedTextField(
                                    value = schedInterval,
                                    onValueChange = {},
                                    readOnly = true,
                                    label = { Text("Interval") },
                                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = expandedInterval) },
                                    modifier = Modifier.menuAnchor().fillMaxWidth(),
                                    shape = RoundedCornerShape(8.dp)
                                )
                                ExposedDropdownMenu(expanded = expandedInterval, onDismissRequest = { expandedInterval = false }) {
                                    listOf("hourly", "daily", "weekly", "monthly").forEach { opt ->
                                        DropdownMenuItem(text = { Text(opt) }, onClick = { schedInterval = opt; expandedInterval = false })
                                    }
                                }
                            }

                            Spacer(modifier = Modifier.height(12.dp))
                            Button(onClick = { createSchedule() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), colors = ButtonDefaults.buttonColors(containerColor = Accent), enabled = schedName.isNotBlank() && schedQuery.isNotBlank() && !creating) {
                                if (creating) CircularProgressIndicator(modifier = Modifier.size(18.dp), color = OnPrimary, strokeWidth = 2.dp)
                                else Text("Create Schedule")
                            }
                        }
                    }
                }
            }

            if (loading) {
                item { Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Accent) } }
            } else if (error != null) {
                item {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = RedBg)) { Text(error ?: "", modifier = Modifier.padding(16.dp), color = Red) }
                    Spacer(modifier = Modifier.height(8.dp))
                    Button(onClick = { loadSchedules() }) { Text("Retry") }
                }
            } else if (schedules.isEmpty()) {
                item { Box(modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp), contentAlignment = Alignment.Center) { Text("No schedules yet", color = Text2) } }
            } else {
                items(schedules) { schedule ->
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Box(
                                    modifier = Modifier
                                        .size(10.dp)
                                        .clip(CircleShape)
                                        .then(
                                            if (schedule.enabled) Modifier
                                            else Modifier
                                        ),
                                    contentAlignment = Alignment.Center
                                ) {
                                    Surface(
                                        modifier = Modifier.size(10.dp),
                                        shape = CircleShape,
                                        color = if (schedule.enabled) Green else Text3
                                    ) {}
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(schedule.name, style = MaterialTheme.typography.titleMedium, color = Text)
                                    Text("${schedule.query} • ${schedule.provider} • ${schedule.interval}", style = MaterialTheme.typography.bodySmall, color = Text3, maxLines = 1)
                                }
                            }

                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Text("Runs: ${schedule.runs}", style = MaterialTheme.typography.labelMedium, color = Text2)
                                Text("Results: ${schedule.results_count}", style = MaterialTheme.typography.labelMedium, color = Text2)
                                schedule.last_run?.let { Text("Last: $it", style = MaterialTheme.typography.labelMedium, color = Text2) }
                            }

                            Spacer(modifier = Modifier.height(8.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                Button(
                                    onClick = { toggleSchedule(schedule) },
                                    colors = ButtonDefaults.buttonColors(containerColor = if (schedule.enabled) Yellow else Green),
                                    shape = RoundedCornerShape(8.dp),
                                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp)
                                ) {
                                    Text(if (schedule.enabled) "Disable" else "Enable", style = MaterialTheme.typography.labelMedium)
                                }
                                if (schedule.results != null && schedule.results!!.isNotEmpty()) {
                                    TextButton(onClick = {
                                        expandedResults = if (expandedResults.contains(schedule.id))
                                            expandedResults - schedule.id
                                        else expandedResults + schedule.id
                                    }) {
                                        Text(if (expandedResults.contains(schedule.id)) "Hide Results" else "View Results", style = MaterialTheme.typography.labelMedium, color = Accent)
                                    }
                                }
                                Spacer(modifier = Modifier.weight(1f))
                                IconButton(onClick = { deleteSchedule(schedule.id) }, modifier = Modifier.size(32.dp)) {
                                    Icon(Icons.Default.Delete, contentDescription = "Delete", tint = Red, modifier = Modifier.size(18.dp))
                                }
                            }

                            if (expandedResults.contains(schedule.id) && schedule.results != null) {
                                Spacer(modifier = Modifier.height(8.dp))
                                Divider(color = Bg3)
                                Spacer(modifier = Modifier.height(8.dp))
                                Text("Results", style = MaterialTheme.typography.titleSmall, color = Text)
                                schedule.results!!.forEach { lead ->
                                    Spacer(modifier = Modifier.height(8.dp))
                                    LeadCard(lead = lead) { }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
