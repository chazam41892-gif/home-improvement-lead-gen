package com.leadgenpro.android.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.leadgenpro.android.api.ApiClient
import com.leadgenpro.android.api.TradeConvertRequest
import com.leadgenpro.android.api.TradeConvertResponse
import com.leadgenpro.android.ui.theme.*
import kotlinx.coroutines.launch

data class PlanOption(
    val key: String,
    val name: String,
    val price: Int,
    val features: List<String>
)

private val plans = listOf(
    PlanOption("starter", "Starter", 97, listOf("Lead capture", "Basic dashboard", "Email support")),
    PlanOption("growth", "Growth", 197, listOf("Everything in Starter", "Advanced analytics", "Priority support", "API access")),
    PlanOption("pro", "Pro", 497, listOf("Everything in Growth", "Dedicated account manager", "Custom integrations", "White-label option"))
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TradeConvertScreen(
    navController: NavController,
    businessName: String,
    phone: String,
    email: String
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()

    var selectedPlan by remember { mutableStateOf(plans[0].key) }
    var converting by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<TradeConvertResponse?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    fun convert() {
        scope.launch {
            converting = true
            error = null
            try {
                val response = ApiClient.getApiService(context).convertLead(
                    TradeConvertRequest(
                        trade = "",
                        businessName = businessName,
                        phone = phone,
                        email = email,
                        plan = selectedPlan
                    )
                )
                if (response.isSuccessful) {
                    result = response.body()
                } else {
                    error = "Error: ${response.code()} ${response.message()}"
                }
            } catch (e: Exception) {
                error = e.message ?: "Conversion failed"
            } finally {
                converting = false
            }
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Convert Lead", fontWeight = FontWeight.Bold) },
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
        if (result?.ok == true) {
            ConversionSuccess(navController = navController, result = result!!, padding = padding)
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .padding(16.dp)
            ) {
                Card(
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = Bg2),
                    border = CardDefaults.outlinedCardBorder().copy(
                        width = 1.dp,
                        brush = androidx.compose.ui.graphics.SolidColor(Bg3.copy(alpha = 0.5f))
                    ),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "Lead Details",
                            style = MaterialTheme.typography.titleMedium,
                            fontWeight = FontWeight.SemiBold,
                            color = Text
                        )
                        Spacer(modifier = Modifier.height(12.dp))
                        DetailRow("Business", businessName)
                        if (phone.isNotBlank()) DetailRow("Phone", phone)
                        if (email.isNotBlank()) DetailRow("Email", email)
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                Text(
                    text = "Select Plan",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = Text
                )
                Spacer(modifier = Modifier.height(12.dp))

                plans.forEach { plan ->
                    Card(
                        onClick = { selectedPlan = plan.key },
                        shape = RoundedCornerShape(12.dp),
                        colors = CardDefaults.cardColors(
                            containerColor = if (selectedPlan == plan.key) Accent.copy(alpha = 0.1f) else Bg2
                        ),
                        border = CardDefaults.outlinedCardBorder().copy(
                            width = if (selectedPlan == plan.key) 2.dp else 1.dp,
                            brush = androidx.compose.ui.graphics.SolidColor(
                                if (selectedPlan == plan.key) Accent else Bg3.copy(alpha = 0.5f)
                            )
                        ),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp)
                    ) {
                        Row(
                            modifier = Modifier
                                .padding(16.dp)
                                .fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text(
                                    text = plan.name,
                                    style = MaterialTheme.typography.titleSmall,
                                    fontWeight = FontWeight.SemiBold,
                                    color = Text
                                )
                                Spacer(modifier = Modifier.height(2.dp))
                                Text(
                                    text = "$${plan.price}/mo",
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    color = Accent
                                )
                            }
                            RadioButton(
                                selected = selectedPlan == plan.key,
                                onClick = { selectedPlan = plan.key },
                                colors = RadioButtonDefaults.colors(selectedColor = Accent)
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(20.dp))

                if (error != null) {
                    Text(text = error ?: "", color = Red, style = MaterialTheme.typography.bodyMedium)
                    Spacer(modifier = Modifier.height(8.dp))
                }

                Button(
                    onClick = { convert() },
                    enabled = !converting,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(52.dp),
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Green)
                ) {
                    if (converting) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = OnPrimary,
                            strokeWidth = 2.dp
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                    }
                    Text("Convert — $${plans.find { it.key == selectedPlan }?.price ?: 0}/mo")
                }
            }
        }
    }
}

@Composable
private fun ConversionSuccess(
    navController: NavController,
    result: TradeConvertResponse,
    padding: PaddingValues
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(padding)
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Icon(
            imageVector = Icons.Default.CheckCircle,
            contentDescription = null,
            tint = Green,
            modifier = Modifier.size(72.dp)
        )
        Spacer(modifier = Modifier.height(20.dp))
        Text(
            text = "Conversion Successful!",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.Bold,
            color = Text
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "${result.lead?.businessName ?: ""} has been onboarded.",
            style = MaterialTheme.typography.bodyLarge,
            color = Text2
        )
        Spacer(modifier = Modifier.height(24.dp))

        result.account?.let { account ->
            Card(
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(containerColor = Bg2),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    SuccessRow("Account ID", account.accountId)
                    SuccessRow("Business", account.businessName)
                    SuccessRow("Status", account.status)
                }
            }
            Spacer(modifier = Modifier.height(12.dp))
        }

        result.subscription?.let { sub ->
            Card(
                shape = RoundedCornerShape(12.dp),
                colors = CardDefaults.cardColors(containerColor = Bg2),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    SuccessRow("Subscription", sub.subscriptionId)
                    SuccessRow("Plan", sub.plan)
                    SuccessRow("Status", sub.status)
                    SuccessRow("Renews", sub.renewsAt)
                }
            }
        }

        Spacer(modifier = Modifier.height(32.dp))

        Button(
            onClick = { navController.popBackStack() },
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Accent)
        ) {
            Text("Done")
        }
    }
}

@Composable
private fun DetailRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text = label, style = MaterialTheme.typography.bodyMedium, color = Text3)
        Text(text = value, style = MaterialTheme.typography.bodyMedium, color = Text)
    }
}

@Composable
private fun SuccessRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text = label, style = MaterialTheme.typography.bodySmall, color = Text3)
        Text(text = value, style = MaterialTheme.typography.bodySmall, color = Text)
    }
}
