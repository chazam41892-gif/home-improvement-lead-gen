package com.leadgenpro.android.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val Background = Bg

private val DarkColorScheme = darkColorScheme(
    primary = Primary,
    onPrimary = OnPrimary,
    primaryContainer = PrimaryContainer,
    onPrimaryContainer = OnPrimaryContainer,
    secondary = Accent2,
    background = Bg,
    surface = Background,
    surfaceVariant = SurfaceVariant,
    onBackground = Text,
    onSurface = Text,
    onSurfaceVariant = Text2,
    outline = Text3
)

@Composable
fun LeadGenProTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = DarkColorScheme,
        typography = Typography,
        content = content
    )
}
