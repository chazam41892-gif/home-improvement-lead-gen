package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.leadgenpro.android.api.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EnrichmentScreen(navController: NavController) {
    val api = remember { ApiClient.create() }
    val scope = rememberCoroutineScope()
    var providers by remember { mutableStateOf<List<EnrichProvider>?>(null) }
    var leads by remember { mutableStateOf<List<Lead>?>(null) }
    var selectedLeadId by remember { mutableStateOf<String?>(null) }
    var enrichResult by remember { mutableStateOf<EnrichResponse?>(null) }
    var batchResults by remember { mutableStateOf<List<EnrichResponse>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        try {
            val pResp = api.getEnrichProviders()
            if (pResp.isSuccessful) providers = pResp.body()?.providers
            val lResp = api.getLeads()
            if (lResp.isSuccessful) leads = lResp.body()?.leads
        } catch (e: Exception) {
            error = "Error: ${e.message}"
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Lead Enrichment") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            // Enrichment Providers status
            item {
                Text("Enrichment Providers", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(8.dp))
                if (providers != null) {
                    providers!!.forEach { p ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(
                                if (p.available) Icons.Default.CheckCircle else Icons.Default.Cancel,
                                contentDescription = null,
                                tint = if (p.available) Color(0xFF00C853) else Color(0xFF9E9E9E),
                                modifier = Modifier.size(16.dp)
                            )
                            Spacer(Modifier.width(8.dp))
                            Text("${p.name}: ${if (p.available) "Available" else "Not configured"}")
                        }
                    }
                } else {
                    CircularProgressIndicator(modifier = Modifier.size(16.dp))
                }
                Spacer(Modifier.height(16.dp))
                HorizontalDivider()
                Spacer(Modifier.height(16.dp))
            }

            // Lead selector
            item {
                Text("Select Lead to Enrich", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(8.dp))
                if (leads.isNullOrEmpty()) {
                    Text("No leads available. Capture leads first.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    leads!!.forEach { lead ->
                        Card(
                            modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
                            colors = CardDefaults.cardColors(
                                containerColor = if (selectedLeadId == lead.id) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant
                            ),
                            onClick = { selectedLeadId = lead.id }
                        ) {
                            Text(
                                "${lead.title} — ${lead.location}",
                                modifier = Modifier.padding(12.dp),
                                style = MaterialTheme.typography.bodyMedium
                            )
                        }
                    }
                    Spacer(Modifier.height(12.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(
                            onClick = {
                                if (selectedLeadId != null) {
                                    loading = true
                                    scope.launch {
                                        try {
                                            val resp = api.enrichFromLead(selectedLeadId!!)
                                            if (resp.isSuccessful) {
                                                enrichResult = EnrichResponse(
                                                    businessName = resp.body()?.businessName ?: "",
                                                    trade = resp.body()?.trade ?: "",
                                                    contactName = resp.body()?.contactName,
                                                    title = resp.body()?.title,
                                                    phone = resp.body()?.phone,
                                                    email = resp.body()?.email,
                                                    address = resp.body()?.address,
                                                    city = resp.body()?.city,
                                                    state = resp.body()?.state,
                                                    zip = resp.body()?.zip,
                                                    website = resp.body()?.website,
                                                    employeeCount = resp.body()?.employeeCount,
                                                    revenue = resp.body()?.revenue,
                                                    yearFounded = resp.body()?.yearFounded,
                                                    sources = resp.body()?.sources ?: emptyList(),
                                                    confidence = resp.body()?.confidence ?: 0.0,
                                                    error = resp.body()?.error
                                                )
                                            } else {
                                                error = "Enrich failed: ${resp.code()}"
                                            }
                                        } catch (e: Exception) {
                                            error = e.message
                                        }
                                        loading = false
                                    }
                                }
                            },
                            enabled = selectedLeadId != null && !loading
                        ) {
                            if (loading) CircularProgressIndicator(modifier = Modifier.size(16.dp), color = Color.White)
                            else Text("Enrich Selected Lead")
                        }
                        OutlinedButton(
                            onClick = {
                                loading = true
                                scope.launch {
                                    try {
                                        val requests = leads!!.map { EnrichRequest(businessName = it.title, trade = it.industry, location = it.location) }
                                        val resp = api.enrichBatch(BatchEnrichRequest(leads = requests))
                                        if (resp.isSuccessful) batchResults = resp.body()?.results
                                        else error = "Batch enrich failed: ${resp.code()}"
                                    } catch (e: Exception) {
                                        error = e.message
                                    }
                                    loading = false
                                }
                            },
                            enabled = !leads.isNullOrEmpty() && !loading
                        ) {
                            Text("Batch Enrich All")
                        }
                    }
                }
                Spacer(Modifier.height(16.dp))
                HorizontalDivider()
                Spacer(Modifier.height(16.dp))
            }

            // Single enrich result
            if (enrichResult != null) {
                item {
                    Text("Enrichment Result", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            if (enrichResult!!.error != null) {
                                Text("Error: ${enrichResult!!.error}", color = Color.Red)
                            }
                            DetailRow("Business", enrichResult!!.businessName)
                            DetailRow("Trade", enrichResult!!.trade)
                            DetailRow("Contact", enrichResult!!.contactName)
                            DetailRow("Title", enrichResult!!.title)
                            DetailRow("Phone", enrichResult!!.phone)
                            DetailRow("Email", enrichResult!!.email)
                            DetailRow("Address", enrichResult!!.address)
                            DetailRow("City", enrichResult!!.city)
                            DetailRow("State", enrichResult!!.state)
                            DetailRow("Zip", enrichResult!!.zip)
                            DetailRow("Website", enrichResult!!.website)
                            DetailRow("Employees", enrichResult!!.employeeCount?.toString())
                            DetailRow("Revenue", enrichResult!!.revenue)
                            DetailRow("Founded", enrichResult!!.yearFounded?.toString())
                            DetailRow("Confidence", "${(enrichResult!!.confidence * 100).toInt()}%")
                            DetailRow("Sources", enrichResult!!.sources.joinToString(", "))
                        }
                    }
                }
            }

            // Batch results
            if (batchResults != null) {
                item {
                    Spacer(Modifier.height(16.dp))
                    Text("Batch Results (${batchResults!!.size})", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                }
                batchResults!!.forEach { r ->
                    item {
                        Card(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                            Column(modifier = Modifier.padding(12.dp)) {
                                Text(r.businessName, fontWeight = FontWeight.Bold)
                                if (r.phone != null) Text("Phone: ${r.phone}", style = MaterialTheme.typography.bodySmall)
                                if (r.email != null) Text("Email: ${r.email}", style = MaterialTheme.typography.bodySmall)
                                if (r.contactName != null) Text("Contact: ${r.contactName}", style = MaterialTheme.typography.bodySmall)
                                Text("Confidence: ${(r.confidence * 100).toInt()}%", style = MaterialTheme.typography.bodySmall)
                                if (r.error != null) Text("Error: ${r.error}", color = Color.Red, style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }

            if (error != null) {
                item {
                    Spacer(Modifier.height(8.dp))
                    Text("Error: $error", color = Color.Red)
                }
            }
        }
    }
}

@Composable
fun DetailRow(label: String, value: String?) {
    if (value != null && value.isNotEmpty()) {
        Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
            Text("$label: ", fontWeight = FontWeight.Medium, style = MaterialTheme.typography.bodySmall, modifier = Modifier.width(80.dp))
            Text(value, style = MaterialTheme.typography.bodySmall)
        }
    }
}
