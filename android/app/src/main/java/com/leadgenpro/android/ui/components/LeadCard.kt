package com.leadgenpro.android.ui.components

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.leadgenpro.android.api.Lead
import com.leadgenpro.android.ui.theme.*

@Composable
fun LeadCard(lead: Lead, onClick: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = Bg2),
        border = CardDefaults.outlinedCardBorder().copy(
            width = 1.dp,
            brush = androidx.compose.ui.graphics.SolidColor(Bg3.copy(alpha = 0.5f))
        )
    ) {
        Column(
            modifier = Modifier.padding(16.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = lead.title,
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                        color = Text,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = lead.source,
                            style = MaterialTheme.typography.labelMedium,
                            color = Text3
                        )
                        if (lead.industry.isNotBlank()) {
                            Text(
                                text = " • ${lead.industry}",
                                style = MaterialTheme.typography.labelMedium,
                                color = Text3
                            )
                        }
                        if (lead.location.isNotBlank()) {
                            Text(
                                text = " • ${lead.location}",
                                style = MaterialTheme.typography.labelMedium,
                                color = Text3
                            )
                        }
                    }
                }
                Spacer(modifier = Modifier.width(12.dp))
                ScoreBadge(score = lead.score)
            }

            if (lead.snippet.isNotBlank()) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = lead.snippet,
                    style = MaterialTheme.typography.bodySmall,
                    color = Text2,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis
                )
            }
        }
    }
}
