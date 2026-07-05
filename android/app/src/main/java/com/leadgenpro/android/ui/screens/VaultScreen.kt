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
fun VaultScreen(navController: NavController) {
    val api = remember { ApiClient.create() }
    val scope = rememberCoroutineScope()
    var vaultKeys by remember { mutableStateOf<Map<String, VaultService>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var selectedService by remember { mutableStateOf<String?>(null) }
    var newKeyValue by remember { mutableStateOf("") }

    LaunchedEffect(Unit) {
        try {
            val resp = api.getVaultKeys()
            if (resp.isSuccessful) vaultKeys = resp.body() ?: emptyMap()
            else error = "Failed to load vault: ${resp.code()}"
        } catch (e: Exception) {
            error = "Error: ${e.message}"
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Key Vault") },
                navigationIcon = {
                    IconButton(onClick = { navController.popBackStack() }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        if (error != null) {
            Text("Error: $error", color = Color.Red, modifier = Modifier.padding(padding).padding(16.dp))
            return@Scaffold
        }
        if (vaultKeys == null) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
            return@Scaffold
        }

        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp)) {
            item {
                Text("API Service Keys", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(4.dp))
                Text("Configure provider keys to unlock enrichment features", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.height(16.dp))
            }

            vaultKeys!!.forEach { (serviceName, service) ->
                item {
                    Card(
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
                    ) {
                        Column(modifier = Modifier.padding(12.dp)) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically
                            ) {
                                Text(serviceName, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleSmall)
                                Surface(
                                    color = if (service.configured) Color(0xFF00C853) else Color(0xFF9E9E9E),
                                    shape = MaterialTheme.shapes.small
                                ) {
                                    Text(
                                        if (service.configured) "Configured" else "Missing",
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                                        color = Color.White,
                                        style = MaterialTheme.typography.labelSmall
                                    )
                                }
                            }
                            Spacer(Modifier.height(4.dp))
                            Text(service.doc, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            if (service.keys.isNotEmpty()) {
                                Text("Key: ${service.keys.first().masked}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurface)
                            }
                            Text("ENV: ${service.envVar}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Spacer(Modifier.height(8.dp))

                            if (selectedService == serviceName) {
                                OutlinedTextField(
                                    value = newKeyValue,
                                    onValueChange = { newKeyValue = it },
                                    label = { Text("Enter API key") },
                                    modifier = Modifier.fillMaxWidth(),
                                    singleLine = true
                                )
                                Spacer(Modifier.height(8.dp))
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    Button(onClick = {
                                        scope.launch {
                                            try {
                                                api.setVaultKey(serviceName, mapOf("key" to newKeyValue))
                                                newKeyValue = ""
                                                selectedService = null
                                                val resp = api.getVaultKeys()
                                                if (resp.isSuccessful) vaultKeys = resp.body()
                                            } catch (e: Exception) {
                                                error = e.message
                                            }
                                        }
                                    }) {
                                        Text("Save Key")
                                    }
                                    if (service.keys.any { it.source == "vault" }) {
                                        OutlinedButton(onClick = {
                                            scope.launch {
                                                try {
                                                    api.deleteVaultKey(serviceName)
                                                    selectedService = null
                                                    val resp = api.getVaultKeys()
                                                    if (resp.isSuccessful) vaultKeys = resp.body()
                                                } catch (e: Exception) {
                                                    error = e.message
                                                }
                                            }
                                        }) {
                                            Text("Delete Key")
                                        }
                                    }
                                    TextButton(onClick = { selectedService = null; newKeyValue = "" }) {
                                        Text("Cancel")
                                    }
                                }
                            } else {
                                Button(onClick = { selectedService = serviceName; newKeyValue = "" }) {
                                    Text("Set Key")
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
