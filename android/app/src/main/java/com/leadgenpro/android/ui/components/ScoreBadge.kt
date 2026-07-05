package com.leadgenpro.android.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.leadgenpro.android.ui.theme.*

@Composable
fun ScoreBadge(score: Double, modifier: Modifier = Modifier) {
    val scoreColor = when {
        score >= 70 -> Green
        score >= 40 -> Yellow
        else -> Red
    }
    val bgColor = when {
        score >= 70 -> GreenBg
        score >= 40 -> YellowBg
        else -> RedBg
    }

    Box(
        modifier = modifier
            .clip(RoundedCornerShape(8.dp))
            .background(bgColor)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = "${score.toInt()}",
            fontSize = 16.sp,
            fontWeight = FontWeight.Bold,
            color = scoreColor
        )
    }
}
