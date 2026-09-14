# VIGILANCE — FabData import rapide et non-régression

Ce fichier est volontairement conservé dans la branche de correction. Toute future optimisation d'import ou reconstruction d'un APK doit respecter ces points avant d'être considérée comme candidate de production.

## Référence fonctionnelle

- Ne jamais repartir du vieux socle `0.21.5` pour fabriquer une candidate destinée à remplacer les versions récentes.
- La branche de référence utilisée ici est `feature/forecast-fixed-lead-h24`, actuellement en `0.23.6`.
- Le précédent APK de test `0.21.5-importfix-test` reste uniquement un banc d'essai de performance. Il ne doit pas devenir une base de développement.

## Cadrans tangentiels — garde-fous obligatoires

Le panneau des cadrans doit conserver simultanément :

- double tap : bascule compact / développé ;
- appui long : ouverture de `Monitoring des cadrans` pour modifier les horizons surveillés ;
- glisser : déplacement du panneau ;
- poignée bas-droite : redimensionnement quand le panneau est développé ;
- persistance de la position, taille et état compact ;
- rafraîchissement des cadrans sans casser les gestes tactiles.

Vérifier en particulier qu'un import, un overlay ou une optimisation R8 ne réintroduit pas un `onTouchEvent` simplifié qui consomme le double tap ou l'appui long.

## Import sauvegarde — invariants

- Accepter les sauvegardes historiques v1/v2/v3/v4 ainsi que le format courant v5.
- Pour v4/v5, valider `BACKUP_END` et les compteurs d'intégrité AVANT toute écriture en base.
- Ne jamais modifier les données RAW/MEASURED historiques en silence.
- Conserver la priorité `MEASURED > RECONSTRUCTED > FORECAST`.
- Conserver les enregistrements supplémentaires gérés par `FabDataBackupV3Support`.
- Ne pas avaler silencieusement toutes les anomalies : garder au minimum la première anomalie avec numéro de ligne, type et message.
- Afficher une progression par enregistrements et pas seulement `fichier 0/1` pendant une grosse restauration.

## Optimisation mesurée — sémantique à préserver

Le chemin rapide MEASURED peut éviter les milliers de requêtes `getOrCreateSensor`, `MAX(timestamp)`, mises à jour de capteur et nettoyages par point. En contrepartie il doit reproduire l'état final du chemin historique :

- une mesure réelle remplace un point calculé au même timestamp ;
- les points calculés du même bucket horaire sont nettoyés en lot ;
- les anciennes prévisions futures déjà présentes avant l'import et rendues obsolètes par les mesures restaurées doivent être supprimées ;
- les prévisions présentes DANS la sauvegarde importée doivent, elles, être conservées/restaurées ;
- une prévision/reconstruction plus ancienne ne doit pas écraser une donnée calculée plus récente lorsque `Source_UpdatedAt_ms` permet de les départager.

## Doutes / tests obligatoires avant production

- Le gros fichier réel d'environ 21 Mo doit être réimporté entièrement et ses compteurs comparés au footer.
- Tester import dans une base vide ET dans une base déjà remplie de forecasts récents.
- Tester que les archives météo, les horizons H+N, les courbes sélectionnables et le replay restent présents après compilation.
- Tester double tap + appui long + drag + resize des cadrans sur téléphone réel.
- Tester export puis réimport immédiat d'une sauvegarde v5.
- Tester au moins une sauvegarde v4 existante.
- R8/shrinkResources restent autorisés, mais la petite taille de l'APK n'est pas une preuve de parité fonctionnelle.
- Si un comportement de la 0.22 binaire et de la branche 0.23.6 diffère, ne pas deviner : noter le point ici et valider sur appareil avant suppression d'un comportement.

## Critère de validation

Une candidate n'est validée que si :

1. elle compile sur le socle récent ;
2. l'import complet termine avec progression visible ;
3. les compteurs d'import sont cohérents ;
4. les cadrans conservent tous leurs gestes ;
5. aucune fonction récente n'a disparu par rapport au socle de référence.
