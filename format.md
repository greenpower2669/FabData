# Format des exports thermo-hygromètre

Ce fichier décrit le format **réellement observé** sur les quatre exports de référence fournis le 19/08/2026.

## Encodage et structure

- Encodage : UTF-8
- Fin de ligne : CRLF
- Séparateur : virgule `,`
- 3 colonnes
- Pas de BOM observé sur les quatre fichiers
- Une ligne de mesure par minute

En-tête exact :

```text
Temps,Température_Celsius,Humidité relative_Pourcentage
```

Exemple de forme d'une ligne :

```text
2026/08/19 11:14,26.1,42.7
```

## Colonne 0 — `Temps`

Format :

```text
yyyy/MM/dd HH:mm
```

Les exports observés sont triés **du plus récent vers le plus ancien**.

Point important : sur les quatre fichiers analysés, la colonne `Temps` forme une grille parfaitement régulière d'une minute :

```text
t0
t0 - 1 min
t0 - 2 min
...
tn
```

Aucun trou et aucun doublon temporel n'a été observé dans ces quatre exports.

FabData traite donc ce format connu de façon spéciale :

1. lecture de `Temps` sur la première ligne de données pour obtenir l'ancre `t0` ;
2. lecture éventuelle de la deuxième ligne uniquement pour confirmer le sens de progression ;
3. reconstruction de l'axe temporel par pas de 60 000 ms ;
4. la colonne `Temps` des lignes suivantes n'est pas reparsée une par une.

Cela évite qu'une variation mineure de parsing de la colonne temporelle bloque toutes les mesures alors que les données utiles sont la température et l'humidité.

Si l'en-tête ne correspond pas exactement à ce format, FabData repasse sur le parseur CSV générique et lit alors le timestamp de chaque ligne.

## Colonne 1 — `Température_Celsius`

- nombre décimal
- séparateur décimal observé : point `.`
- précision observée : 0,1 °C

Exemple de forme :

```text
28.0
```

## Colonne 2 — `Humidité relative_Pourcentage`

- nombre décimal
- séparateur décimal observé : point `.`
- précision observée : 0,1 %
- domaine attendu par FabData : 0 à 100 %

Exemple de forme :

```text
43.0
```

## Ordre et taille des quatre fichiers de référence

Les quatre fichiers sont continus à exactement une mesure par minute :

| Capteur | Mesures | Première date chronologique | Dernière date chronologique |
|---|---:|---|---|
| Thermo-hygromètre | 920 | 2026/08/18 19:53 | 2026/08/19 11:12 |
| Thermo-hygromètre 2 | 919 | 2026/08/18 19:55 | 2026/08/19 11:13 |
| Thermo-hygromètre 3 | 917 | 2026/08/18 19:57 | 2026/08/19 11:13 |
| Thermo-hygromètre 4 | 914 | 2026/08/18 20:01 | 2026/08/19 11:14 |

## Identification du capteur

Le capteur est identifié par la partie du nom de fichier située avant `_Exporter`.

Exemples :

```text
Thermo-hygromètre_Exporter...
Thermo-hygromètre 2_Exporter...
Thermo-hygromètre 3_Exporter...
Thermo-hygromètre 4_Exporter...
```

Un export ultérieur couvrant une autre période conserve donc le même capteur.

## Import incrémental

La clé logique en base est :

```text
(capteur, timestamp)
```

Conséquences :

- une date déjà présente n'est pas dupliquée ;
- une nouvelle période du même capteur complète l'historique ;
- un export partiellement chevauchant ajoute uniquement les timestamps manquants ;
- l'ordre des lignes dans le fichier n'a pas d'importance pour la base SQLite.

## Fichiers incomplets / format différent

Le mode à pas fixe de 1 minute n'est utilisé que pour l'en-tête exact documenté ci-dessus.

Pour tout autre format, FabData utilise le parseur générique et ne suppose pas que les timestamps sont continus.
