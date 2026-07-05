package com.leadgenpro.android

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.ui.navigation.AppNavigation
import com.leadgenpro.android.ui.theme.Accent
import com.leadgenpro.android.ui.theme.LeadGenProTheme
import com.leadgenpro.android.ui.theme.Text2
import com.leadgenpro.android.update.ApkDownloader
import com.leadgenpro.android.update.UpdateChecker
import com.leadgenpro.android.update.UpdateInfo
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            LeadGenProTheme {
                MainScreen()
            }
        }
    }
}

@Composable
private fun MainScreen() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snackbarHostState = remember { SnackbarHostState() }
    var updateInfo by remember { mutableStateOf<UpdateInfo?>(null) }
    var showRequiredUpdate by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        val prefs = context.getSharedPreferences("leadgen_prefs", Context.MODE_PRIVATE)
        val lastCheck = prefs.getLong("last_update_check", 0)
        val now = System.currentTimeMillis()
        if (now - lastCheck > 24 * 60 * 60 * 1000L) {
            prefs.edit().putLong("last_update_check", now).apply()
            UpdateChecker.checkForUpdate(
                currentVersionCode = BuildConfig.VERSION_CODE
            ) { info ->
                if (info != null && info.versionCode > BuildConfig.VERSION_CODE) {
                    updateInfo = info
                    if (info.required) {
                        showRequiredUpdate = true
                    } else {
                        scope.launch {
                            snackbarHostState.showSnackbar("Update v${info.latestVersion} available")
                        }
                    }
                }
            }
        }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        Scaffold(
            snackbarHost = { SnackbarHost(snackbarHostState) }
        ) { padding ->
            Box(modifier = Modifier.padding(padding)) {
                AppNavigation()
            }
        }
    }

    if (showRequiredUpdate && updateInfo != null) {
        AlertDialog(
            onDismissRequest = { showRequiredUpdate = false },
            title = { Text("Required Update Available", style = MaterialTheme.typography.headlineSmall) },
            text = {
                Column {
                    Text(
                        "Version ${updateInfo!!.latestVersion} is required to continue.",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    if (updateInfo!!.releaseNotes.isNotBlank()) {
                        Spacer(modifier = Modifier.height(12.dp))
                        Text(
                            updateInfo!!.releaseNotes,
                            style = MaterialTheme.typography.bodySmall,
                            color = Text2
                        )
                    }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        updateInfo?.let {
                            ApkDownloader.downloadAndInstall(context, it.downloadUrl)
                        }
                        showRequiredUpdate = false
                    },
                    shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Accent)
                ) {
                    Text("Download Update")
                }
            },
            dismissButton = {
                TextButton(onClick = { showRequiredUpdate = false }) {
                    Text("Later", color = Text2)
                }
            }
        )
    }
}
