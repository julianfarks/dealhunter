package com.dealhunter.ai.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val Blue = Color(0xFF3D7BFF)
val Violet = Color(0xFF8B5CF6)
val Good = Color(0xFF2ECC8F)
val Warn = Color(0xFFFFB020)
val Bad = Color(0xFFFF5D73)

private val Dark = darkColorScheme(
    primary = Blue, onPrimary = Color.White, secondary = Violet, onSecondary = Color.White,
    tertiary = Color(0xFF22D3EE), background = Color(0xFF0B0F1A), onBackground = Color(0xFFE8ECF8),
    surface = Color(0xFF141A2B), onSurface = Color(0xFFE8ECF8), surfaceVariant = Color(0xFF1C2338),
    onSurfaceVariant = Color(0xFFA9B3CF), outline = Color(0xFF39425E), error = Bad,
)
private val Light = lightColorScheme(
    primary = Color(0xFF2563EB), onPrimary = Color.White, secondary = Color(0xFF7C3AED), onSecondary = Color.White,
    tertiary = Color(0xFF0891B2), background = Color(0xFFF5F7FC), onBackground = Color(0xFF0B0F1A),
    surface = Color.White, onSurface = Color(0xFF0B0F1A), surfaceVariant = Color(0xFFE9EDF8),
    onSurfaceVariant = Color(0xFF4A5473), outline = Color(0xFFC3CBE0), error = Color(0xFFD62F4B),
)

@Composable
fun DealHunterTheme(mode: String, content: @Composable () -> Unit) {
    val dark = when (mode) {
        "light" -> false
        "system" -> isSystemInDarkTheme()
        else -> true
    }
    MaterialTheme(colorScheme = if (dark) Dark else Light, content = content)
}
