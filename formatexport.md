# Format de sauvegarde / réimport FabData

Ce fichier décrit le format CSV de sauvegarde complète introduit en **FabData v0.5**.

Objectif : permettre de passer d'une version APK à une autre sans perdre :

- les capteurs ;
- le nom des pièces ;
- les couleurs ;
- toutes les mesures température / humidité ;
- les événements / annotations créés dans FabData.

Le même bouton **Importer CSV** accepte les exports thermo-hygromètre d'origine et les sauvegardes FabData décrites ici.

## Encodage

- UTF-8
- séparateur virgule `,`
- champs contenant virgule, guillemet ou retour ligne protégés selon les règles CSV classiques
- un enregistrement logique par ligne ; une note contenant un retour à la ligne reste correctement protégée entre guillemets et le parseur FabData la restitue intégralement

## En-tête exact

```text
FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms
```

## Types d'enregistrements

La première colonne `FabData_Record` indique le rôle de chaque ligne.

### `META`

Informations générales sur la sauvegarde. Cette ligne peut être ignorée par une ancienne version du lecteur si elle ne contient aucune donnée utile.

### `SENSOR`

Décrit un capteur et son paramétrage :

- `Capteur_ID` : identifiant stable ;
- `Capteur` : nom affiché ;
- `Piece` : pièce associée ;
- `Couleur` : index de couleur 0 à 7.

Le réimport retrouve d'abord le capteur grâce à `Capteur_ID`, puis remet son nom, sa pièce et sa couleur.

### `SAMPLE`

Une mesure thermo-hygrométrique :

- `Capteur_ID` ;
- `Temps_Epoch_ms` ;
- `Temps` lisible humainement ;
- `Temperature_Celsius` ;
- `Humidite_relative_Pourcentage`.

La clé anti-doublon reste :

```text
Capteur_ID + timestamp
```

Un réimport du même fichier complète donc la base sans multiplier les mesures existantes.

### `EVENT`

Une annotation / un événement créé dans FabData :

- capteur éventuellement associé ;
- pièce ;
- date/heure ;
- titre ;
- note complète, y compris les retours à la ligne ;
- type d'événement ;
- date de dernière modification.

Un événement réimporté est considéré comme déjà présent si les éléments suivants correspondent :

```text
timestamp + titre + note + capteur + pièce + type
```

Cela permet de réimporter plusieurs fois une sauvegarde sans créer une pile d'événements identiques.

## Temps

Deux représentations sont conservées :

- `Temps_Epoch_ms` : valeur de référence exacte en millisecondes depuis l'époque Unix ;
- `Temps` : représentation lisible `yyyy/MM/dd HH:mm:ss`.

À l'import, `Temps_Epoch_ms` est prioritaire. `Temps` sert de secours et de lecture humaine.

## Exemple simplifié

```csv
FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms
META,1,,FabData,,,,,,,,Sauvegarde complète FabData,,,
SENSOR,1,thermohygrometre2,Thermo-hygromètre 2,Chambre,2,,,,,,,,
SAMPLE,1,thermohygrometre2,Thermo-hygromètre 2,Chambre,2,1787137200000,2026/08/19 12:00:00,27.1,42.6,,,,
EVENT,1,thermohygrometre2,Thermo-hygromètre 2,Chambre,2,1787137200000,2026/08/19 12:00:00,,,Fenêtre ouverte,Aération,ventilation,1787137300000
```

## Compatibilité entre versions

`Format_Version` vaut actuellement `1`.

Les évolutions futures doivent conserver la lecture des colonnes existantes et ajouter de nouvelles colonnes de façon compatible autant que possible.

Une version qui ne reconnaît pas un numéro de format ne doit pas importer silencieusement des données potentiellement mal interprétées.

## Important pour les APK de développement

La sauvegarde CSV est indépendante de la base SQLite interne et de la signature APK. Elle sert donc de fichier de transfert entre installations et versions de développement.

Procédure recommandée :

1. dans l'ancienne version, utiliser **Sauvegarder / Exporter** ;
2. conserver le fichier `FabData_sauvegarde_*.csv` ;
3. installer la nouvelle version ;
4. utiliser **Importer CSV** ;
5. sélectionner le fichier de sauvegarde ;
6. FabData restaure les mesures, pièces, couleurs et événements en évitant les doublons.
