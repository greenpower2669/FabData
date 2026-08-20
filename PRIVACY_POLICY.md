# Politique de confidentialité — FabData

Dernière mise à jour : 20 août 2026

## Éditeur

FabData est développé et publié par **FabData / greenpower2669**.

Contact confidentialité : via le dépôt public GitHub `greenpower2669/FabData` et son système d'issues.

## Données traitées

FabData sert à importer, conserver, visualiser et annoter localement des relevés de température et d'humidité.

L'application peut traiter les données que l'utilisateur choisit lui-même d'importer dans des fichiers CSV, notamment :

- date et heure des mesures ;
- température ;
- humidité relative ;
- nom du capteur ;
- nom de la pièce ;
- annotations et événements saisis par l'utilisateur.

FabData v0.8 peut également télécharger les observations météorologiques publiques de la station Météo-France Lyon-Bron afin de créer localement la sonde virtuelle **Lyon**. Seules les valeurs météo publiques nécessaires au graphique (heure, température et humidité) sont enregistrées dans la base locale FabData.

## Collecte et partage

Dans la version actuelle de FabData :

- aucune mesure, annotation, pièce ou sauvegarde utilisateur n'est envoyée à un serveur FabData ;
- aucune donnée utilisateur n'est vendue ;
- aucune donnée utilisateur n'est partagée avec un tiers par l'application ;
- aucun compte utilisateur n'est créé ;
- aucun SDK publicitaire ou analytique n'est intégré ;
- l'application ne demande pas l'accès à la localisation, au microphone, à la caméra, aux contacts ou aux journaux d'appels.

Pour alimenter la sonde **Lyon**, l'application effectue une requête HTTPS vers une page publique Infoclimat présentant les observations de la station Météo-France Lyon-Bron. Comme pour toute connexion Internet, le serveur distant peut techniquement recevoir les informations réseau standard nécessaires à la requête, notamment l'adresse IP et les en-têtes HTTP. FabData n'ajoute à cette requête aucune mesure locale, annotation, nom de pièce, sauvegarde ou identifiant utilisateur.

Les données de l'utilisateur sont conservées localement sur l'appareil Android dans la base interne de l'application. Les sauvegardes CSV ne sont créées que lorsque l'utilisateur demande explicitement un export et choisit lui-même leur emplacement via le sélecteur de fichiers Android.

## Accès aux fichiers

FabData utilise le sélecteur de fichiers Android pour permettre à l'utilisateur de choisir les CSV à importer ou l'emplacement d'un fichier de sauvegarde à exporter. L'application n'effectue pas de balayage général du stockage de l'appareil.

## Conservation et suppression

Les mesures, paramètres et événements restent enregistrés localement jusqu'à ce que l'utilisateur les supprime, vide la base depuis les réglages de FabData, efface les données de l'application depuis Android ou désinstalle l'application.

Les fichiers CSV exportés sont sous le contrôle de l'utilisateur et doivent être supprimés manuellement depuis l'emplacement où ils ont été enregistrés.

## Sécurité

FabData limite le traitement aux données nécessaires à ses fonctions d'analyse et de visualisation. Les données personnelles ou mesures locales de l'utilisateur ne sont pas transférées par la fonction météo ; seule une consultation HTTPS d'une ressource météo publique est réalisée.

## Services de distribution

Google Play peut traiter certaines données liées au téléchargement, à l'installation, aux statistiques de la fiche Play Store ou au compte Google de l'utilisateur selon les propres règles de confidentialité de Google. Ces traitements sont réalisés par Google et non par FabData.

## Évolution de l'application

Si une future version ajoute une synchronisation cloud des données utilisateur, de l'analytique, de la publicité ou tout autre traitement supplémentaire, cette politique et la déclaration « Sécurité des données » de Google Play devront être mises à jour avant publication.
