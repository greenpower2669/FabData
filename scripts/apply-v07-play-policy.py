from pathlib import Path

path = Path("app/src/main/java/com/fabdata/app/MainActivity.kt")
text = path.read_text(encoding="utf-8")

marker = "Politique de confidentialité · FabData v0.7"
if marker in text:
    print("FabData v0.7 privacy patch already applied")
    raise SystemExit(0)

old = '''        title = { Text("Réglages FabData") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
'''
new = '''        title = { Text("Réglages FabData") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
'''
if old not in text:
    raise SystemExit("Settings dialog block not found")
text = text.replace(old, new, 1)

old2 = '''                HorizontalDivider()
                TextButton(onClick = onClear) {
                    Text("Vider toute la base locale", color = MaterialTheme.colorScheme.error)
                }
'''
new2 = '''                HorizontalDivider()
                Text("Politique de confidentialité · FabData v0.7", fontWeight = FontWeight.Bold)
                Text(
                    "Les mesures, noms de pièces et événements sont traités localement sur cet appareil. " +
                        "FabData n'envoie aucune donnée utilisateur à un serveur, n'intègre ni publicité ni analytique " +
                        "et ne crée aucun compte utilisateur.",
                    style = MaterialTheme.typography.bodySmall
                )
                Text(
                    "Les imports et sauvegardes CSV sont déclenchés explicitement par l'utilisateur via le sélecteur " +
                        "de fichiers Android. Contact confidentialité : dépôt GitHub greenpower2669/FabData.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                HorizontalDivider()
                TextButton(onClick = onClear) {
                    Text("Vider toute la base locale", color = MaterialTheme.colorScheme.error)
                }
'''
if old2 not in text:
    raise SystemExit("Clear database block not found")
text = text.replace(old2, new2, 1)

path.write_text(text, encoding="utf-8")
print("FabData v0.7 in-app privacy policy added")
