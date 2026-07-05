package com.leadgenpro.android.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.Lead
import com.leadgenpro.android.ui.components.InfoRow
import com.leadgenpro.android.ui.components.ScoreBadge
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeadDetailScreen(leadId: String, navController: NavController) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var lead by remember { mutableStateOf<Lead?>(null) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(leadId) {
        scope.launch {
            loading = true
            try {
                val response = ApiClient.getApiService(context).getLead(leadId)
                if (response.isSuccessful) {
                    lead = response.body()
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

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Lead Detail", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
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
                modifier = Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator(color = Accent)
            }
        } else if (error != null) {
            Box(
                modifier = Modifier.fillMaxSize().padding(padding),
                contentAlignment = Alignment.Center
            ) {
                Text(text = error ?: "", color = Red)
            }
        } else if (lead != null) {
            val l = lead!!
            LazyColumn(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    Card(
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(containerColor = Bg2)
                    ) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Row(
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                                modifier = Modifier.fillMaxWidth()
                            ) {
                                Text(
                                    text = l.title,
                                    style = MaterialTheme.typography.titleLarge,
                                    color = Text,
                                    modifier = Modifier.weight(1f)
                                )
                                Spacer(modifier = Modifier.width(12.dp))
                                ScoreBadge(score = l.score)
                            }

                            Spacer(modifier = Modifier.height(12.dp))
                            InfoRow("Source", l.source)
                            InfoRow("Industry", l.industry)
                            InfoRow("Location", l.location)
                            InfoRow("URL", l.url)
                            l.created_at?.let { InfoRow("Created", it) }
                        }
                    }
                }

                l.score_breakdown?.let { breakdown ->
                    item {
                        Card(
                            shape = RoundedCornerShape(12.dp),
                            colors = CardDefaults.cardColors(containerColor = Bg2)
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = "Score Breakdown",
                                    style = MaterialTheme.typography.titleMedium,
                                    color = Text
                                )
                                Spacer(modifier = Modifier.height(12.dp))
                                ScoreBar("Relevance", breakdown.relevance)
                                ScoreBar("Intent", breakdown.intent)
                                ScoreBar("Fit", breakdown.fit)
                                ScoreBar("Urgency", breakdown.urgency)
                                ScoreBar("Budget", breakdown.budget)
                            }
                        }
                    }
                }

                if (!l.email.isNullOrBlank() || !l.phone.isNullOrBlank()) {
                    item {
                        Card(
                            shape = RoundedCornerShape(12.dp),
                            colors = CardDefaults.cardColors(containerColor = Bg2)
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = "Contact",
                                    style = MaterialTheme.typography.titleMedium,
                                    color = Text
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                l.email?.let { InfoRow("Email", it) }
                                l.phone?.let { InfoRow("Phone", it) }
                            }
                        }
                    }
                }

                if (!l.snippet.isNullOrBlank()) {
                    item {
                        Card(
                            shape = RoundedCornerShape(12.dp),
                            colors = CardDefaults.cardColors(containerColor = Bg2)
                        ) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text(
                                    text = "Notes",
                                    style = MaterialTheme.typography.titleMedium,
                                    color = Text
                                )
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = l.snippet,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = Text2
                                )
                            }
                        }
                    }
                }

                item {
                    Row(
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        if (l.url.isNotBlank()) {
                            Button(
                                onClick = {
                                    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(l.url))
                                    context.startActivity(intent)
                                },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(12.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Accent)
                            ) {
                                Icon(Icons.Default.OpenInNew, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("Open URL")
                            }
                        }
                        if (!l.phone.isNullOrBlank()) {
                            Button(
                                onClick = {
                                    val intent = Intent(Intent.ACTION_DIAL, Uri.parse("tel:${l.phone}"))
                                    context.startActivity(intent)
                                },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(12.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Green)
                            ) {
                                Icon(Icons.Default.Phone, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("Call")
                            }
                        }
                        if (!l.email.isNullOrBlank()) {
                            Button(
                                onClick = {
                                    val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:${l.email}"))
                                    context.startActivity(intent)
                                },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(12.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Accent2)
                            ) {
                                Icon(Icons.Default.Email, contentDescription = null, modifier = Modifier.size(18.dp))
                                Spacer(modifier = Modifier.width(4.dp))
                                Text("Email")
                            }
                        }
                    }
                }

                item { Spacer(modifier = Modifier.height(32.dp)) }
            }
        }
    }
}

@Composable
private fun ScoreBar(label: String, value: Double) {
    Column(modifier = Modifier.padding(vertical = 4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(text = label, style = MaterialTheme.typography.bodyMedium, color = Text2)
            Text(text = "${value.toInt()}/100", style = MaterialTheme.typography.bodyMedium, color = Text)
        }
        Spacer(modifier = Modifier.height(4.dp))
        val scoreColor = when {
            value >= 70 -> Green
            value >= 40 -> Yellow
            else -> Red
        }
        LinearProgressIndicator(
            progress = { (value / 100f).toFloat() },
            modifier = Modifier
                .fillMaxWidth()
                .height(6.dp),
            color = scoreColor,
            trackColor = Bg3,
            strokeCap = StrokeCap.Round
        )
    }
}
