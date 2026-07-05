package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.TradeConfig
import com.leadgenpro.android.api.TradeDiscoveryRequest
import com.leadgenpro.android.api.TradeLeadResponse
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TradeDiscoveryScreen(navController: NavController) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var trades by remember { mutableStateOf<List<TradeConfig>>(emptyList()) }
    var leads by remember { mutableStateOf<List<TradeLeadResponse>>(emptyList()) }
    var selectedTrade by remember { mutableStateOf<String?>(null) }
    var location by remember { mutableStateOf("") }
    var loadingTrades by remember { mutableStateOf(true) }
    var discovering by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var tradeDropdownExpanded by remember { mutableStateOf(false) }

    fun loadTrades() {
        scope.launch {
            loadingTrades = true
            try {
                val response = ApiClient.getApiService(context).getTrades()
                if (response.isSuccessful) {
                    trades = response.body()?.trades ?: emptyList()
                } else {
                    error = "Error: ${response.code()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Connection failed"
            } finally {
                loadingTrades = false
            }
        }
    }

    fun discover() {
        val trade = selectedTrade ?: return
        if (location.isBlank()) return
        scope.launch {
            discovering = true
            error = null
            try {
                val response = ApiClient.getApiService(context).discoverLeads(
                    TradeDiscoveryRequest(trade = trade, location = location)
                )
                if (response.isSuccessful) {
                    leads = response.body() ?: emptyList()
                } else {
                    error = "Error: ${response.code()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Discovery failed"
            } finally {
                discovering = false
            }
        }
    }

    LaunchedEffect(Unit) {
        loadTrades()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Discover Trades", fontWeight = FontWeight.Bold) },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                },
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
                .padding(16.dp)
        ) {
            ExposedDropdownMenuBox(
                expanded = tradeDropdownExpanded,
                onExpandedChange = { tradeDropdownExpanded = it }
            ) {
                OutlinedTextField(
                    value = selectedTrade ?: "",
                    onValueChange = {},
                    readOnly = true,
                    label = { Text("Trade") },
                    placeholder = { Text("Select a trade") },
                    trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded = tradeDropdownExpanded) },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = Text,
                        unfocusedTextColor = Text,
                        focusedLabelColor = Accent,
                        unfocusedLabelColor = Text3,
                        focusedBorderColor = Accent,
                        unfocusedBorderColor = Bg3,
                        cursorColor = Accent
                    ),
                    modifier = Modifier
                        .menuAnchor()
                        .fillMaxWidth()
                )
                ExposedDropdownMenu(
                    expanded = tradeDropdownExpanded,
                    onDismissRequest = { tradeDropdownExpanded = false },
                    modifier = Modifier.widthIn(max = 400.dp)
                ) {
                    trades.forEach { trade ->
                        DropdownMenuItem(
                            text = { Text(trade.name) },
                            onClick = {
                                selectedTrade = trade.name
                                tradeDropdownExpanded = false
                            }
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            OutlinedTextField(
                value = location,
                onValueChange = { location = it },
                label = { Text("Location") },
                placeholder = { Text("e.g. Austin, TX") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { discover() }),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedTextColor = Text,
                    unfocusedTextColor = Text,
                    focusedLabelColor = Accent,
                    unfocusedLabelColor = Text3,
                    focusedBorderColor = Accent,
                    unfocusedBorderColor = Bg3,
                    cursorColor = Accent
                ),
                modifier = Modifier.fillMaxWidth()
            )

            Spacer(modifier = Modifier.height(16.dp))

            Button(
                onClick = { discover() },
                enabled = selectedTrade != null && location.isNotBlank() && !discovering,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Accent)
            ) {
                if (discovering) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(20.dp),
                        color = OnPrimary,
                        strokeWidth = 2.dp
                    )
                    Spacer(modifier = Modifier.width(8.dp))
                }
                Text("Discover")
            }

            Spacer(modifier = Modifier.height(16.dp))

            if (error != null) {
                Card(
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = RedBg)
                ) {
                    Text(
                        text = error ?: "",
                        color = Red,
                        modifier = Modifier.padding(16.dp),
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
                Spacer(modifier = Modifier.height(12.dp))
            }

            if (leads.isNotEmpty()) {
                Text(
                    text = "${leads.size} leads found",
                    style = MaterialTheme.typography.titleMedium,
                    color = Text2
                )
                Spacer(modifier = Modifier.height(8.dp))

                LazyColumn(
                    verticalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    items(leads) { lead ->
                        TradeLeadCard(lead = lead) {
                            navController.navigate("trade_convert/${lead.businessName}/${lead.phone}/${lead.email}")
                        }
                    }
                }
            } else if (!discovering && selectedTrade != null && leads.isEmpty()) {
                Text(
                    text = "Run a discovery to find leads",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Text3
                )
            }
        }
    }
}

@Composable
private fun TradeLeadCard(lead: TradeLeadResponse, onConvert: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Bg2),
        border = CardDefaults.outlinedCardBorder().copy(
            width = 1.dp,
            brush = androidx.compose.ui.graphics.SolidColor(Bg3.copy(alpha = 0.5f))
        )
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = lead.businessName,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = Text
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    if (lead.source.isNotBlank()) {
                        Text(
                            text = lead.source,
                            style = MaterialTheme.typography.labelMedium,
                            color = Text3
                        )
                    }
                }
                if (lead.score > 0) {
                    Card(
                        shape = RoundedCornerShape(8.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (lead.score >= 70) GreenBg else if (lead.score >= 40) YellowBg else RedBg
                        )
                    ) {
                        Text(
                            text = "${lead.score.toInt()}",
                            style = MaterialTheme.typography.labelLarge,
                            fontWeight = FontWeight.Bold,
                            color = if (lead.score >= 70) Green else if (lead.score >= 40) Yellow else Red,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp)
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            if (lead.phone.isNotBlank() || lead.email.isNotBlank()) {
                Text(
                    text = listOfNotNull(
                        lead.phone.takeIf { it.isNotBlank() },
                        lead.email.takeIf { it.isNotBlank() }
                    ).joinToString(" • "),
                    style = MaterialTheme.typography.bodySmall,
                    color = Text2
                )
                Spacer(modifier = Modifier.height(8.dp))
            }

            Button(
                onClick = onConvert,
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Green)
            ) {
                Text("Convert to Account")
            }
        }
    }
}
