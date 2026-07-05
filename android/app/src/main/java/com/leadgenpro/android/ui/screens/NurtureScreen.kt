package com.leadgenpro.android.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.NurtureSequence
import com.leadgenpro.android.api.NurtureStats
import com.leadgenpro.android.api.StatsResponse
import com.leadgenpro.android.ui.components.StatCard
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NurtureScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var sequences by remember { mutableStateOf<List<NurtureSequence>>(emptyList()) }
    var stats by remember { mutableStateOf<NurtureStats?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var expandedSeq by remember { mutableStateOf<Set<String>>(emptySet()) }

    fun loadData() {
        scope.launch {
            loading = true
            error = null
            try {
                val api = ApiClient.getApiService(context)
                val seqResp = api.listNurtureSequences()
                val statsResp = api.getStats()
                if (seqResp.isSuccessful) {
                    sequences = seqResp.body() ?: emptyList()
                }
                if (statsResp.isSuccessful) {
                    stats = statsResp.body()?.nurture
                }
            } catch (e: Exception) {
                error = e.message ?: "Connection failed"
            } finally {
                loading = false
            }
        }
    }

    LaunchedEffect(Unit) { loadData() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Nurture", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg, titleContentColor = Text)
            )
        }
    ) { padding ->
        if (loading) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Accent)
            }
        } else if (error != null) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(text = error ?: "", color = Red)
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = { loadData() }) { Text("Retry") }
                }
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                item {
                    Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
                        StatCard(
                            label = "Total",
                            value = "${stats?.total_sequences ?: 0}",
                            color = Accent,
                            modifier = Modifier.weight(1f)
                        )
                        StatCard(
                            label = "Active",
                            value = "${stats?.active ?: 0}",
                            color = Green,
                            modifier = Modifier.weight(1f)
                        )
                        StatCard(
                            label = "Completed",
                            value = "${stats?.completed ?: 0}",
                            color = Accent2,
                            modifier = Modifier.weight(1f)
                        )
                    }
                }

                if (sequences.isEmpty()) {
                    item {
                        Box(modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp), contentAlignment = Alignment.Center) {
                            Text("No nurture sequences yet", color = Text2)
                        }
                    }
                } else {
                    item {
                        Text("Sequences", style = MaterialTheme.typography.titleMedium, color = Text)
                    }

                    items(sequences) { seq ->
                        Card(
                            shape = RoundedCornerShape(12.dp),
                            colors = CardDefaults.cardColors(containerColor = Bg2),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Column(modifier = Modifier.weight(1f)) {
                                        Text(seq.lead_name, style = MaterialTheme.typography.titleMedium, color = Text)
                                        Text(seq.lead_industry, style = MaterialTheme.typography.bodySmall, color = Text3)
                                    }
                                    if (seq.completed) {
                                        Icon(Icons.Default.CheckCircle, contentDescription = "Completed", tint = Green)
                                    } else {
                                        Text("Step ${seq.current_step + 1}/${seq.steps.size}", style = MaterialTheme.typography.labelMedium, color = Yellow)
                                    }
                                }

                                Spacer(modifier = Modifier.height(8.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    seq.steps.forEachIndexed { index, step ->
                                        Surface(
                                            shape = RoundedCornerShape(6.dp),
                                            color = when {
                                                step.sent -> GreenBg
                                                index == seq.current_step -> YellowBg
                                                else -> Bg3
                                            }
                                        ) {
                                            Row(modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp)) {
                                                Text(
                                                    text = when (step.type) {
                                                        "sms" -> "SMS"
                                                        "email" -> "Email"
                                                        "call" -> "Call"
                                                        else -> step.type
                                                    },
                                                    style = MaterialTheme.typography.labelSmall,
                                                    color = when {
                                                        step.sent -> Green
                                                        index == seq.current_step -> Yellow
                                                        else -> Text3
                                                    }
                                                )
                                                if (step.sent) {
                                                    Spacer(modifier = Modifier.width(4.dp))
                                                    Icon(Icons.Default.CheckCircle, contentDescription = null, tint = Green, modifier = Modifier.size(12.dp))
                                                }
                                            }
                                        }
                                    }
                                }

                                if (seq.steps.isNotEmpty()) {
                                    Spacer(modifier = Modifier.height(8.dp))
                                    TextButton(onClick = {
                                        expandedSeq = if (expandedSeq.contains(seq.id))
                                            expandedSeq - seq.id
                                        else expandedSeq + seq.id
                                    }) {
                                        Text(if (expandedSeq.contains(seq.id)) "Hide details" else "View details", color = Accent)
                                    }

                                    AnimatedVisibility(visible = expandedSeq.contains(seq.id)) {
                                        Column {
                                            seq.steps.forEachIndexed { index, step ->
                                                Spacer(modifier = Modifier.height(8.dp))
                                                Surface(shape = RoundedCornerShape(8.dp), color = Bg3) {
                                                    Column(modifier = Modifier.padding(12.dp)) {
                                                        Text(
                                                            text = "${index + 1}. ${step.type.uppercase()}",
                                                            style = MaterialTheme.typography.labelMedium,
                                                            color = if (step.sent) Green else if (index == seq.current_step) Yellow else Text2
                                                        )
                                                        Text(step.content, style = MaterialTheme.typography.bodySmall, color = Text2)
                                                        step.scheduled_at?.let {
                                                            Text("Scheduled: $it", style = MaterialTheme.typography.labelSmall, color = Text3)
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                stats?.let { s ->
                    if (s.upcoming_appointments > 0) {
                        item {
                            Spacer(modifier = Modifier.height(8.dp))
                            Text("Upcoming Appointments", style = MaterialTheme.typography.titleMedium, color = Text)
                        }
                        item {
                            Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                                Row(modifier = Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                                    Icon(Icons.Default.Schedule, contentDescription = null, tint = Accent)
                                    Spacer(modifier = Modifier.width(8.dp))
                                    Text("${s.upcoming_appointments} appointments scheduled", style = MaterialTheme.typography.bodyMedium, color = Text)
                                }
                            }
                        }
                    }
                }

                item { Spacer(modifier = Modifier.height(32.dp)) }
            }
        }
    }
}
