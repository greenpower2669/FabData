# VIGILANCE — FabData v0.23.9 import performant et non-régression

Ce fichier accompagne la branche de correction et sert de garde-fou. Toute optimisation d'import doit rester strictement additive par rapport au build de référence v0.23.9.

## Référence fonctionnelle exacte

- APK de référence utilisateur : `FabData-v0.23.9-release-deterministic-slots.apk` (~70,23 Mo).
- Source de référence : branche `feature/forecast-fixed-lead-h24`.
- Commit de référence : `b6df81544f28e7faf3e9dfe4059c6e3353bc9460` — `Bind forecast rows to the claimed canonical slot [skip ci]`.
- `app/build.gradle.kts` : versionCode 66, versionName `0.23.9`.
- Branche de travail : `fix/v0239-import-performance-safe`, créée directement depuis ce commit.
- Les anciennes branches/tests `0.21.5-importfix-test` et `fix/v0236-import-fast-regression-guard` ne sont PAS des bases de production. Elles peuvent servir uniquement de documentation sur les idées d'optimisation.

## Principe de correction

- Ne pas reconstruire les fonctions 0.23.9 une par une.
- Ne pas cherry-pick globalement l'ancienne branche d'import rapide.
- Partir de la 0.23.9 intacte et modifier uniquement le chemin d'import/restauration nécessaire.
- Toute modification doit pouvoir être expliquée comme une optimisation locale, sans toucher aux cadrans, prévisions, slots, UI, navigation, archives ni calculs météo/thermiques.

## Cadrans tangentiels — garde-fous obligatoires

Le panneau des cadrans doit conserver simultanément :

- double tap : bascule compact / développé ;
- appui long : ouverture de `Monitoring des cadrans` pour modifier les horizons surveillés ;
- glisser : déplacement du panneau ;
- poignée bas-droite : redimensionnement quand le panneau est développé ;
- persistance de la position, taille et état compact ;
- rafraîchissement sans casser les gestes tactiles.

## Import sauvegarde — invariants

- Accepter les sauvegardes historiques supportées par la 0.23.9, notamment v1/v2/v3/v4/v5 si présentes dans le code de référence.
- Pour les formats avec footer d'intégrité, valider `BACKUP_END` et les compteurs AVANT toute écriture.
- Ne jamais modifier silencieusement les RAW/MEASURED historiques.
- Conserver la priorité `MEASURED > RECONSTRUCTED > FORECAST`.
- Conserver tous les enregistrements étendus gérés par `FabDataBackupV3Support` et les modules de prévisions/archives actuels.
- Les lignes JSON de courbes/archives déjà contenues dans le backup doivent être restaurées directement par leur store. Ne pas ajouter une seconde vérification lourde, un recalcul de courbe ou un appel météo pendant l'import : l'intégrité du backup + le parseur typé existant font foi.
- `UI_PREFERENCES` doit conserver la personnalisation de l'interface et des cadrans. Les fichiers de préférences FabData liés aux animations/mouvements/transitions doivent également être inclus, sans jamais inclure credential/token/secret/password/auth.
- Une erreur de ligne ne doit pas disparaître silencieusement : garder au minimum la première anomalie avec ligne/type/message.
- La progression d'un gros backup doit porter sur les enregistrements réels, pas rester uniquement à `0/1 fichier`.

## Performance — points de vigilance

- Éviter un `getOrCreateSensor` et une mise à jour de capteur pour chaque mesure ; utiliser un cache local par `stableKey` pendant l'import.
- Éviter les nettoyages SQLite lourds point par point lorsque l'état final peut être obtenu par une opération set-based équivalente.
- Ne pas relancer une réconciliation globale identique une fois par sonde si la requête couvre déjà toutes les sondes de la période.
- Ne jamais optimiser au prix de la sémantique des forecasts : les forecasts réellement contenus dans la sauvegarde doivent survivre, les forecasts préexistants rendus obsolètes doivent être traités comme dans le chemin de référence.
- Ne pas toucher aux slots déterministes/canoniques de la 0.23.9.

## Tests obligatoires avant candidate

- Import du gros backup réel (~23 Mo) dans une base vide.
- Import du même backup dans une base déjà remplie.
- Comparaison des compteurs avec le footer.
- Vérification que la progression évolue rapidement après la phase de lecture/validation.
- Test d'une sauvegarde v4 historique.
- Export v5 puis réimport immédiat.
- Vérification des cadrans : double tap, appui long, déplacement, resize, persistance.
- Vérification de la restauration des personnalisations/animations.
- Vérification des archives météo, horizons H+N, courbes sélectionnables, replay et slots déterministes.
- Comparaison visuelle/fonctionnelle avec l'APK v0.23.9 de référence avant toute promotion.

## Critère de validation

Une candidate est acceptable uniquement si :

1. elle dérive du commit v0.23.9 de référence ci-dessus ;
2. l'import complet termine avec progression visible ;
3. les compteurs sont cohérents ;
4. aucun geste ou cadran n'a régressé ;
5. aucune fonction récente n'a disparu ;
6. les slots déterministes restent identiques au build de référence.
