# VIGILANCE — FabData v0.23.9 import performant et non-régression

Ce fichier accompagne la branche de correction et sert de garde-fou. Toute optimisation d'import ou d'interface doit rester strictement additive par rapport au build de référence v0.23.9.

## Référence fonctionnelle exacte

- APK de référence utilisateur : `FabData-v0.23.9-release-deterministic-slots.apk` (~70,23 Mo).
- Source de référence : branche `feature/forecast-fixed-lead-h24`.
- Commit de référence : `b6df81544f28e7faf3e9dfe4059c6e3353bc9460` — `Bind forecast rows to the claimed canonical slot [skip ci]`.
- `app/build.gradle.kts` : versionCode 66, versionName `0.23.9`.
- Base import optimisée : `fix/v0239-import-performance-safe`.
- Branche UI actuelle : `feature/v0239-compact-cascade-ui`, dérivée de l'import optimisé validé.
- Les anciennes branches/tests `0.21.5-importfix-test` et `fix/v0236-import-fast-regression-guard` ne sont PAS des bases de production.

## Principe de correction

- Ne pas reconstruire les fonctions 0.23.9 une par une.
- Ne pas cherry-pick globalement l'ancienne branche d'import rapide.
- Conserver deterministic slots, archives, courbes météo/Fab, moteurs thermiques et RAW.
- Les changements UI doivent réorganiser l'affichage sans modifier la sémantique scientifique des données.

## Cadrans tangentiels — garde-fous obligatoires

Le panneau des cadrans doit conserver simultanément :

- démarrage de chaque nouvelle Activity en mode réduit/compact ;
- double tap : bascule compact / développé ;
- appui long : ouverture de `Monitoring des cadrans` pour modifier les horizons surveillés ;
- glisser : déplacement du panneau ;
- poignée bas-droite : redimensionnement quand le panneau est développé ;
- persistance de la position et de la géométrie développée ;
- rafraîchissement sans casser les gestes tactiles.

## Cascade temporelle — garde-fous UI

- Les quatre niveaux doivent rester groupés en haut et proches visuellement :
  1. totalité / navigation giga ;
  2. sélection du haut / zoom large ;
  3. exploration ;
  4. graphe détaillé RAW + prévisions.
- Aucun bloc d'aide, choix de période ou outil d'analyse ne doit se glisser entre le niveau 3 et le graphe détaillé.
- `Sélectionner une période`, Aide et Alertes restent sous le graphe détaillé.
- Les presets du graphe détaillé (`1 h`, `24 h`, `48 h`, `1 sem.`, `1 mois`) restent sous le graphe, hors de sa carte.
- Le bandeau d'exploration garde les boutons/flèches de page ET accepte un glissement continu au-delà du bord pour demander la même page précédente/suivante.
- La navigation visuelle peut aller jusqu'à `maintenant + 48 h` : le terrain s'arrête à sa dernière donnée, les prévisions peuvent continuer à sa suite.
- L'extension H+48 est une borne d'affichage/navigation ; elle ne doit jamais inventer de terrain RAW.

## Gestes du graphe détaillé

- tap simple : curseur ;
- double tap : événement / interaction annotation existante ;
- pince + glisse : ajustement/navigation ;
- appui long : événement technique conservé mais aucune action visible pour l'instant ;
- ne pas réintroduire automatiquement l'ancien zoom 48 h sur appui long sans décision explicite.

## Import sauvegarde — invariants

- Accepter les sauvegardes historiques supportées par la 0.23.9, notamment v1/v2/v3/v4/v5 si présentes dans le code de référence.
- Pour les formats avec footer d'intégrité, valider `BACKUP_END` et les compteurs AVANT toute écriture.
- Ne jamais modifier silencieusement les RAW/MEASURED historiques.
- Conserver la priorité `MEASURED > RECONSTRUCTED > FORECAST`.
- Conserver tous les enregistrements étendus gérés par `FabDataBackupV3Support` et les modules de prévisions/archives actuels.
- Les lignes JSON de courbes/archives déjà contenues dans le backup doivent être restaurées directement par leur store. Ne pas ajouter une seconde vérification lourde, un recalcul de courbe ou un appel météo pendant l'import.
- `UI_PREFERENCES` doit conserver la personnalisation de l'interface et des cadrans. Les fichiers de préférences FabData liés aux animations/mouvements/transitions doivent également être inclus, sans credential/token/secret/password/auth.
- Une erreur de ligne ne doit pas disparaître silencieusement : garder au minimum la première anomalie avec ligne/type/message.
- La progression d'un gros backup doit porter sur les enregistrements réels, pas rester uniquement à `0/1 fichier`.

## Performance — points de vigilance

- Éviter un `getOrCreateSensor` et une mise à jour de capteur pour chaque mesure ; utiliser un cache local par `stableKey` pendant l'import.
- Éviter les nettoyages SQLite lourds point par point lorsque l'état final peut être obtenu par une opération set-based équivalente.
- Ne pas relancer une réconciliation globale identique une fois par sonde si la requête couvre déjà toutes les sondes de la période.
- Ne jamais optimiser au prix de la sémantique des forecasts : les forecasts réellement contenus dans la sauvegarde doivent survivre, les forecasts préexistants rendus obsolètes doivent être traités comme dans le chemin de référence.
- Ne pas toucher aux slots déterministes/canoniques de la 0.23.9.

## Tests obligatoires avant candidate

- Import du gros backup réel (~23 Mo) dans une base vide et dans une base déjà remplie.
- Comparaison des compteurs avec le footer ; test v4 historique ; export v5 puis réimport.
- Vérification restauration personnalisations/animations.
- Vérification des archives météo, horizons H+N, courbes sélectionnables, replay et slots déterministes.
- Cadrans : démarrage compact, double tap, appui long, déplacement, resize.
- Cascade : quatre niveaux contigus ; graphe détail juste sous exploration ; contrôles sous le détail.
- Navigation jusqu'à H+48 avec terrain qui s'arrête au présent et prévisions qui continuent.
- Bandeau exploration : boutons ET glissement continu aux bords.
- Graphe détaillé : appui long sans action visible, double tap événement toujours fonctionnel.
- Comparaison visuelle/fonctionnelle avec l'APK v0.23.9 de référence avant toute promotion.

## Critère de validation

Une candidate est acceptable uniquement si :

1. elle dérive de la lignée v0.23.9 deterministic-slots ;
2. l'import complet termine avec progression visible ;
3. les compteurs sont cohérents ;
4. aucun geste ou cadran n'a régressé ;
5. aucune fonction récente n'a disparu ;
6. les slots déterministes restent identiques au build de référence ;
7. la cascade UI et la navigation H+48 respectent les invariants ci-dessus.
