package com.dealhunter.ai.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.dp
import com.dealhunter.ai.data.HistoryPoint

/** Gráfico de precios real: sólo dibuja observaciones guardadas; no interpola ni inventa puntos. */
@Composable
fun PriceChart(points: List<HistoryPoint>, currency: String?, modifier: Modifier = Modifier) {
    val vals = points.mapNotNull { it.price.toDoubleOrNull() }
    if (vals.isEmpty()) return
    var selected by remember(points) { mutableStateOf(points.lastIndex) }
    val line = MaterialTheme.colorScheme.primary
    val violet = MaterialTheme.colorScheme.secondary
    val grid = MaterialTheme.colorScheme.outline.copy(alpha = 0.4f)
    val min = vals.min()
    val max = vals.max()
    val span = if (max - min < 1e-9) 1.0 else max - min

    Column(modifier) {
        val p = points.getOrNull(selected)
        Text(
            if (p != null) "${money(p.price, currency)} · ${dateTime(p.at)}" else "",
            style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurface,
        )
        Canvas(
            Modifier.fillMaxWidth().height(180.dp)
                .pointerInput(points) {
                    detectTapGestures { o -> selected = nearest(o.x, size.width.toFloat(), points.size) }
                }
                .pointerInput(points) {
                    detectDragGestures { change, _ -> selected = nearest(change.position.x, size.width.toFloat(), points.size) }
                }
        ) {
            val padV = 12f
            val w = size.width
            val h = size.height - padV * 2
            fun x(i: Int) = if (vals.size == 1) w / 2 else w * i / (vals.size - 1)
            fun y(v: Double) = (padV + h - ((v - min) / span * h)).toFloat()
            for (g in 0..3) {
                val gy = padV + h * g / 3
                drawLine(grid, Offset(0f, gy), Offset(w, gy), strokeWidth = 1f)
            }
            val path = Path()
            vals.forEachIndexed { i, v -> if (i == 0) path.moveTo(x(i), y(v)) else path.lineTo(x(i), y(v)) }
            val fill = Path().apply {
                addPath(path)
                lineTo(x(vals.lastIndex), size.height)
                lineTo(x(0), size.height)
                close()
            }
            drawPath(fill, Brush.verticalGradient(listOf(line.copy(alpha = 0.30f), Color.Transparent)))
            drawPath(path, Brush.horizontalGradient(listOf(line, violet)), style = Stroke(width = 5f, cap = StrokeCap.Round))
            vals.forEachIndexed { i, v -> if (vals.size <= 40) drawCircle(line, 5f, Offset(x(i), y(v))) }
            val si = selected.coerceIn(0, vals.lastIndex)
            drawLine(violet.copy(alpha = 0.6f), Offset(x(si), 0f), Offset(x(si), size.height), strokeWidth = 2f)
            drawCircle(violet, 10f, Offset(x(si), y(vals[si])))
        }
    }
}

private fun nearest(px: Float, width: Float, n: Int): Int {
    if (n <= 1 || width <= 0f) return 0
    return Math.round((px / width).coerceIn(0f, 1f) * (n - 1))
}
