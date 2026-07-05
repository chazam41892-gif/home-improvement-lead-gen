package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.BuildConfig
import com.leadgenpro.android.api.BusinessConfig
import com.leadgenpro.android.update.ApkDownloader
import com.leadgenpro.android.update.UpdateChecker
import com.leadgenpro.android.update.UpdateInfo
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var serverUrl by remember { mutableStateOf("") }
    var config by remember { mutableStateOf<BusinessConfig?>(null) }
    var metrics by remember { mutableStateOf<BusinessConfig?>(null) }
    var loading by remember { mutableStateOf(true) }
    var saveMessage by remember { mutableStateOf<String?>(null) }
    var showResetDialog by remember { mutableStateOf(false) }

    var avgJobSize by remember { mutableStateOf("") }
    var grossMargin by remember { mutableStateOf("") }
    var leadCostCeiling by remember { mutableStateOf("") }
    var monthlyAdBudget by remember { mutableStateOf("") }
    var targetRoas by remember { mutableStateOf("") }
    var bizName by remember { mutableStateOf("") }
    var bizPhone by remember { mutableStateOf("") }
    var bizEmail by remember { mutableStateOf("") }

    var updateChecking by remember { mutableStateOf(false) }
    var updateChecked by remember { mutableStateOf(false) }
    var updateInfo by remember { mutableStateOf<UpdateInfo?>(null) }
    var updateUrl by remember {
        mutableStateOf("https://your-domain.com/updates/android/latest.json")
    }

    fun saveUpdateUrl(url: String) {
        context.getSharedPreferences("leadgen_prefs", Context.MODE_PRIVATE)
            .edit().putString("update_url", url).apply()
    }

    fun checkForUpdates() {
        updateChecking = true
        updateChecked = true
        updateInfo = null
        UpdateChecker.checkForUpdate(
            currentVersionCode = BuildConfig.VERSION_CODE,
            updateUrl = updateUrl
        ) { info ->
            updateChecking = false
            updateInfo = info
        }
    }

    fun loadData() {
        scope.launch {
            loading = true
            serverUrl = ApiClient.getBaseUrl(context).removeSuffix("/")
            try {
                val api = ApiClient.getApiService(context)
                val configResp = api.getBusinessConfig()
                val metricsResp = api.getBusinessMetrics()
                if (configResp.isSuccessful) {
                    config = configResp.body()?.config
                    config?.let { c ->
                        avgJobSize = c.avg_job_size.toString()
                        grossMargin = c.gross_margin.toString()
                        leadCostCeiling = c.lead_cost_ceiling.toString()
                        monthlyAdBudget = c.monthly_ad_budget.toString()
                        targetRoas = c.target_roas.toString()
                        bizName = c.business_name
                        bizPhone = c.business_phone
                        bizEmail = c.business_email
                    }
                }
                if (metricsResp.isSuccessful) {
                    metrics = metricsResp.body()
                }
            } catch (_: Exception) { } finally {
                loading = false
            }
        }
    }

    fun saveConfig() {
        scope.launch {
            try {
                val updated = BusinessConfig(
                    avg_job_size = avgJobSize.toDoubleOrNull() ?: 0.0,
                    gross_margin = grossMargin.toDoubleOrNull() ?: 0.0,
                    lead_cost_ceiling = leadCostCeiling.toDoubleOrNull() ?: 0.0,
                    monthly_ad_budget = monthlyAdBudget.toDoubleOrNull() ?: 0.0,
                    target_roas = targetRoas.toDoubleOrNull() ?: 0.0,
                    business_name = bizName,
                    business_phone = bizPhone,
                    business_email = bizEmail
                )
                val response = ApiClient.getApiService(context).updateBusinessConfig(updated)
                if (response.isSuccessful) {
                    saveMessage = "Saved successfully"
                    loadData()
                } else {
                    saveMessage = "Error: ${response.code()}"
                }
            } catch (e: Exception) {
                saveMessage = e.message ?: "Failed to save"
            }
        }
    }

    fun saveServerUrl() {
        ApiClient.updateBaseUrl(context, serverUrl)
        saveMessage = "Server URL updated"
        loadData()
    }

    fun resetAll() {
        ApiClient.resetBaseUrl(context)
        serverUrl = ApiClient.getBaseUrl(context).removeSuffix("/")
        saveMessage = "Reset to defaults"
        loadData()
    }

    LaunchedEffect(Unit) { loadData() }

    LaunchedEffect(Unit) {
        val prefs = context.getSharedPreferences("leadgen_prefs", Context.MODE_PRIVATE)
        updateUrl = prefs.getString("update_url", updateUrl) ?: updateUrl
        checkForUpdates()
    }

    if (showResetDialog) {
        AlertDialog(
            onDismissRequest = { showResetDialog = false },
            title = { Text("Reset All") },
            text = { Text("Reset server URL to default?") },
            confirmButton = {
                TextButton(onClick = { showResetDialog = false; resetAll() }) {
                    Text("Reset", color = Red)
                }
            },
            dismissButton = {
                TextButton(onClick = { showResetDialog = false }) {
                    Text("Cancel")
                }
            }
        )
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Settings", fontWeight = FontWeight.Bold) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Bg, titleContentColor = Text)
            )
        }
    ) { padding ->
        if (loading) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Accent)
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("Server Connection", style = MaterialTheme.typography.titleMedium, color = Text)
                            Spacer(modifier = Modifier.height(8.dp))
                            OutlinedTextField(value = serverUrl, onValueChange = { serverUrl = it }, label = { Text("Server URL") }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
                            Spacer(modifier = Modifier.height(8.dp))
                            Button(onClick = { saveServerUrl() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), colors = ButtonDefaults.buttonColors(containerColor = Accent)) {
                                Text("Save")
                            }
                        }
                    }
                }

                item {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("API Key Status", style = MaterialTheme.typography.titleMedium, color = Text)
                            Spacer(modifier = Modifier.height(8.dp))
                            ApiKeyStatus("Exa", true)
                            ApiKeyStatus("Perplexity", false)
                            ApiKeyStatus("OpenAI", false)
                            ApiKeyStatus("Claude", false)
                        }
                    }
                }

                item {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("Business Config", style = MaterialTheme.typography.titleMedium, color = Text)
                            Spacer(modifier = Modifier.height(8.dp))
                            ConfigField("Business Name", bizName, { bizName = it })
                            ConfigField("Business Phone", bizPhone, { bizPhone = it })
                            ConfigField("Business Email", bizEmail, { bizEmail = it })
                            ConfigField("Avg Job Size (\$)", avgJobSize, { avgJobSize = it })
                            ConfigField("Gross Margin (%)", grossMargin, { grossMargin = it })
                            ConfigField("Lead Cost Ceiling (\$)", leadCostCeiling, { leadCostCeiling = it })
                            ConfigField("Monthly Ad Budget (\$)", monthlyAdBudget, { monthlyAdBudget = it })
                            ConfigField("Target ROAS", targetRoas, { targetRoas = it })
                            Spacer(modifier = Modifier.height(12.dp))
                            Button(onClick = { saveConfig() }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), colors = ButtonDefaults.buttonColors(containerColor = Accent)) {
                                Text("Save Business Config")
                            }
                        }
                    }
                }

                metrics?.let { m ->
                    item {
                        Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                            Column(modifier = Modifier.padding(16.dp)) {
                                Text("Metrics", style = MaterialTheme.typography.titleMedium, color = Text)
                                Spacer(modifier = Modifier.height(8.dp))
                                MetricRow("Profit/Job", "$${String.format("%.2f", m.profit_per_job)}")
                                MetricRow("CAC", "$${String.format("%.2f", m.cac)}")
                                MetricRow("Max CPC", "$${String.format("%.2f", m.max_cpc)}")
                                MetricRow("Break-Even Leads", "${m.break_even_leads}")
                            }
                        }
                    }
                }

                item {
                    Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Bg2)) {
                        Column(modifier = Modifier.padding(16.dp)) {
                            Text("Updates", style = MaterialTheme.typography.titleMedium, color = Text)
                            Spacer(modifier = Modifier.height(8.dp))
                            OutlinedTextField(
                                value = updateUrl,
                                onValueChange = { updateUrl = it; saveUpdateUrl(it) },
                                label = { Text("Update URL") },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                singleLine = true
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            Button(
                                onClick = { checkForUpdates() },
                                modifier = Modifier.fillMaxWidth(),
                                shape = RoundedCornerShape(8.dp),
                                colors = ButtonDefaults.buttonColors(containerColor = Accent),
                                enabled = !updateChecking
                            ) {
                                if (updateChecking) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(18.dp),
                                        color = OnPrimary,
                                        strokeWidth = 2.dp
                                    )
                                } else {
                                    Text("Check for Updates")
                                }
                            }
                            if (updateChecked && !updateChecking) {
                                Spacer(modifier = Modifier.height(8.dp))
                                Text(
                                    text = when {
                                        updateInfo != null -> "Update available: v${updateInfo!!.latestVersion}"
                                        else -> "Up to date (v${BuildConfig.VERSION_NAME})"
                                    },
                                    color = if (updateInfo != null) Green else Text2,
                                    style = MaterialTheme.typography.bodyMedium
                                )
                                if (updateInfo != null) {
                                    Spacer(modifier = Modifier.height(8.dp))
                                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.fillMaxWidth()) {
                                        Button(
                                            onClick = {
                                                ApkDownloader.downloadAndInstall(context, updateInfo!!.downloadUrl)
                                            },
                                            modifier = Modifier.weight(1f),
                                            shape = RoundedCornerShape(8.dp),
                                            colors = ButtonDefaults.buttonColors(containerColor = Green)
                                        ) {
                                            Text("Download v${updateInfo!!.latestVersion}")
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                item {
                    OutlinedButton(
                        onClick = { showResetDialog = true },
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(8.dp),
                        colors = ButtonDefaults.outlinedButtonColors(contentColor = Red)
                    ) {
                        Text("Reset All")
                    }
                }

                item {
                    Text(
                        text = "Lead Gen Pro v1.0.0",
                        style = MaterialTheme.typography.bodySmall,
                        color = Text3,
                        modifier = Modifier.fillMaxWidth().wrapContentWidth(Alignment.CenterHorizontally)
                    )
                }

                if (saveMessage != null) {
                    item {
                        Card(shape = RoundedCornerShape(8.dp), colors = CardDefaults.cardColors(containerColor = GreenBg)) {
                            Text(saveMessage ?: "", modifier = Modifier.padding(12.dp), color = Green)
                        }
                    }
                }

                item { Spacer(modifier = Modifier.height(32.dp)) }
            }
        }
    }
}

@Composable
private fun ApiKeyStatus(service: String, configured: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 4.dp)) {
        Icon(
            if (configured) Icons.Default.CheckCircle else Icons.Default.Error,
            contentDescription = null,
            tint = if (configured) Green else Red,
            modifier = Modifier.size(18.dp)
        )
        Spacer(modifier = Modifier.width(8.dp))
        Text(service, style = MaterialTheme.typography.bodyMedium, color = Text)
        Spacer(modifier = Modifier.weight(1f))
        Text(if (configured) "Configured" else "Not configured", style = MaterialTheme.typography.labelSmall, color = if (configured) Green else Text3)
    }
}

@Composable
private fun ConfigField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, modifier = Modifier.fillMaxWidth(), shape = RoundedCornerShape(8.dp), singleLine = true)
    Spacer(modifier = Modifier.height(6.dp))
}

@Composable
private fun MetricRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = Text2)
        Text(value, style = MaterialTheme.typography.bodyMedium, color = Green)
    }
}
