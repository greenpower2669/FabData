# FabData — À surveiller pour la reprise du 31 août 2026

## Hypothèse principale retenue

Hypothèse 1 à vérifier en priorité : **les données et annotations anciennes sont probablement encore présentes dans SQLite, mais ne sont plus affichées parce que la fenêtre temporelle active les exclut.**

Le code actuel charge uniquement les mesures et annotations comprises dans la période `chosen`, elle-même calculée à partir de la borne temporelle globale la plus récente de la base. Comme cette borne inclut aussi Lyon et les sondes HTTP distantes, l'arrivée de nouvelles mesures météo peut faire glisser la fenêtre visible et faire disparaître visuellement des données anciennes sans les supprimer physiquement.

La liste d'annotations située sous le graphique reçoit actuellement la même liste déjà filtrée par période. Descendre jusqu'en bas de l'écran ne permet donc pas de retrouver une annotation hors de la fenêtre `chosen`.

## À vérifier avant toute modification

1. Faire une sauvegarde complète FabData de la base existante.
2. Compter dans SQLite :
   - nombre total de sondes ;
   - nombre total de mesures ;
   - première et dernière date stockées ;
   - nombre total d'annotations ;
   - première et dernière date des annotations.
3. Comparer ces bornes avec la fenêtre actuellement affichée.
4. Vérifier spécifiquement les anciennes annotations visibles sur les captures précédentes.
5. Vérifier la présence de la « partie 2 » des courbes qui semble avoir disparu.
6. Ne rien supprimer, fusionner ou réécrire avant ce diagnostic.

## Correction d'affichage prévue

Séparer clairement :

- **historique réellement stocké** ;
- **fenêtre actuellement affichée**.

Ajouter un mode `Tout l'historique / Ajuster à toutes les données`.

La section d'annotations devra pouvoir proposer au minimum :

- `Annotations de la période` ;
- `Toutes les annotations`.

Une annotation hors zoom ne doit jamais donner l'impression d'avoir été supprimée.

## Format/import temporel à corriger

Point à surveiller séparément : l'importeur du format thermo reconnu reconstruit actuellement les timestamps à partir de la première ligne avec un pas fixe de 60 secondes, après avoir seulement déterminé le sens grâce à la seconde ligne.

Cela peut être incorrect si le fichier contient :

- une minute manquante ;
- un trou d'enregistrement ;
- une coupure ;
- deux blocs discontinus ;
- des intervalles irréguliers.

Dans ces cas, une partie ultérieure de la courbe peut être artificiellement rapprochée ou déplacée dans le temps.

### Correction souhaitée

Pour chaque ligne CSV, utiliser **le timestamp réellement présent dans cette ligne** dès qu'il est valide.

Le pas artificiel de 60 secondes ne doit servir qu'en secours très encadré si le format source ne fournit réellement pas de timestamp exploitable.

Ne jamais inventer une continuité temporelle lorsqu'un trou réel existe.

## Identité des sondes à vérifier

L'identité d'un thermomètre importé est actuellement dérivée du nom de fichier. Surveiller le cas où un même appareil exporté sous un nom différent crée une nouvelle `stableKey` et sépare artificiellement son historique entre plusieurs pseudo-capteurs.

Ne pas fusionner automatiquement. Détecter et proposer une fusion contrôlée seulement après diagnostic.

## Règles de sécurité pour la reprise

- zéro migration destructive ;
- zéro `drop/recreate` silencieux ;
- zéro suppression automatique pour « réparer » ;
- sauvegarde avant migration ;
- transaction + rollback en cas d'incohérence ;
- vérifier les comptes avant/après migration ;
- préserver le format de sauvegarde FabData actuel tant qu'aucune évolution volontaire n'est décidée.

## Priorité au 31 août

1. Sauvegarder la base actuelle.
2. Auditer SQLite et confirmer ou infirmer l'hypothèse 1.
3. Si les données sont présentes : corriger l'affichage/fenêtrage sans toucher aux données.
4. Corriger ensuite l'import temporel pour respecter chaque timestamp réel.
5. Seulement après : reprendre le checkpoint EVO (zoom 48 h, curseur, étiquettes, styles, auras, opacité, etc.).

## Règle d'or

**Une donnée stockée ne doit jamais sembler perdue simplement parce qu'elle n'est plus dans la fenêtre actuellement affichée.**
