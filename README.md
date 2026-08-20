# FabData

FabData est une application Android de suivi thermo-hygrométrique local avec courbes, événements, imports CSV et sauvegardes réimportables.

## v0.8 — sonde Lyon

- Ajoute une sonde météo virtuelle **Lyon** basée sur les observations de la station **Météo-France Lyon-Bron (MF69029001 / 07480)** affichées par Infoclimat.
- Récupère les mesures horaires déjà publiées pour la journée : température et humidité relative.
- Synchronisation silencieuse au démarrage ; une absence de réseau ne bloque jamais FabData.
- Le bouton **Actualiser** synchronise Lyon puis recharge les courbes.
- Anti-doublon identique aux capteurs physiques : `(capteur, timestamp)`.
- La sonde Lyon utilise le modèle existant `Sensor/Sample` : aucune migration de base n'est nécessaire.
- **Compatibilité sauvegarde conservée** : le format FabData reste `Format_Version = 1` et l'en-tête existant n'est pas modifié.
- Les anciennes sauvegardes FabData v0.5/v0.6/v0.7 restent importables ; les nouvelles sauvegardes incluent Lyon comme un capteur normal.
- Accès Internet limité à la consultation de la ressource météo publique ; aucune mesure locale, annotation ou sauvegarde utilisateur n'est envoyée.

## Fonctions principales

- Import multi-fichiers CSV via le sélecteur Android.
- Identification automatique des thermo-hygromètres depuis les noms de fichiers.
- Base SQLite incrémentale et réimports chevauchants sans doublons.
- Onglets **Heure / Jour / Semaine / Mois / Année**.
- Zoom temporel, déplacement horizontal et remise à zéro du graphique.
- Superposition température / humidité de plusieurs pièces et capteurs.
- Sélection indépendante T° / humidité par capteur.
- Curseur d'inspection et mesure la plus proche.
- Événements / annotations liés à une date, pièce et éventuellement un capteur.
- Sauvegarde complète capteurs + pièces + couleurs + mesures + événements.

## Format thermo-hygromètre reconnu

```text
Temps,Température_Celsius,Humidité relative_Pourcentage
2026/08/19 11:14,26.1,42.7
```

FabData accepte aussi plusieurs alias anglais, séparateurs courants et formats date/heure usuels.

## Format de sauvegarde FabData

Le format complet est documenté dans `formatexport.md` et reste actuellement en **version 1**.

```text
FabData_Record,Format_Version,Capteur_ID,Capteur,Piece,Couleur,Temps_Epoch_ms,Temps,Temperature_Celsius,Humidite_relative_Pourcentage,Titre,Note,Type,UpdatedAt_Epoch_ms
```

Types de lignes : `META`, `SENSOR`, `SAMPLE`, `EVENT`.

## Build

La branche de développement v0.8 est :

`agent/v0.8-lyon-weather`

GitHub Actions produit :

- `artifacts/FabData-v0.8-release.apk`
- `artifacts/FabData-v0.8-release.aab`
