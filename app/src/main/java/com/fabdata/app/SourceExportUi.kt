package com.fabdata.app

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun SourceAwareExportCard(db: FabDataDb) {
    val context = LocalContext.current
    val exporter = remember { FabDataSourceExporter(context, db) }
    val scope = rememberCoroutineScope()
    var includeReconstructed by remember { mutableStateOf(false) }
    var includeForecast by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("Par défaut : données réelles uniquement") }

    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/csv")) { uri ->
        if (uri != null) {
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching { exporter.export(uri, includeReconstructed, includeForecast) }
                }
                message = result.fold(
                    onSuccess = { "Export : ${it.rows} point(s) · ${it.reconstructed} reconstruit(s) · ${it.forecast} prévision(s)" },
                    onFailure = { "Export impossible : ${it.message ?: "erreur inconnue"}" }
                )
            }
        }
    }

    Card(shape = RoundedCornerShape(20.dp)) {
        Column(
            Modifier.fillMaxWidth().padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text("Export des données", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
            Text(
                "Une vraie mesure reste la valeur exportée par défaut. Les données calculées sont facultatives et portent leur colonne source.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = includeReconstructed, onCheckedChange = { includeReconstructed = it })
                Text("Inclure données reconstruites")
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = includeForecast, onCheckedChange = { includeForecast = it })
                Text("Inclure prévisions")
            }
            Button(
                onClick = { launcher.launch("FabData_donnees.csv") },
                modifier = Modifier.fillMaxWidth()
            ) { Text("Exporter les données") }
            Text(message, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
