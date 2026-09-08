# FabData v0.20 — murs extérieurs, sondes et reconstruction

## Objectif

Étendre le moteur inertiel v0.19.8 sans casser son comportement actuel. Le modèle existant reste le fallback lorsque l'utilisateur ne renseigne aucun pan de mur.

## Invariants non négociables

- Une mesure réelle (`MEASURED`) n'est jamais écrasée par une reconstruction ou une prévision.
- `MEASURED > RECONSTRUCTED > FORECAST` reste la règle de priorité.
- La station météo officielle reste la référence extérieure longue. Les sondes locales ne remplacent pas cette référence.
- La dalle / masse inertielle existante reste présente.
- La masse cachée résiduelle reste présente même lorsque des murs deviennent explicites : elle continue à représenter la continuité de dalle vers les voisins, plafonds/dalles intermédiaires, structure hors zone et toute masse non expliquée.
- À information égale à v0.19.8, le nouveau moteur doit pouvoir retomber sur le comportement v0.19.8.
- Maximum 4 pans de mur explicites.

## Rôle des sondes

Chaque sonde possède un rôle thermique persistant :

- `INDOOR` : candidate comme sonde intérieure cible du moteur thermique ;
- `OUTDOOR` : mesure extérieure locale, jamais candidate comme sonde intérieure ;
- `UNDEFINED` : affichable mais exclue du moteur jusqu'à classification ;
- `SYSTEM_REFERENCE` : source système/référence, séparée des sondes ordinaires.

Migration : les sondes physiques existantes avant v0.20 restent `INDOOR` afin de préserver le comportement actuel. Les nouvelles sondes CSV ordinaires démarrent `UNDEFINED`, pour éviter qu'une sonde extérieure nouvellement importée soit prise pour une sonde intérieure.

Une sonde extérieure peut préciser :

- air extérieur de référence locale ;
- microclimat/façade ;
- surface ;
- non précisé.

## Personnalisation bâtiment

Après la personnalisation bâtiment, permettre de définir jusqu'à 4 pans. Pour chaque pan :

- nom ;
- surface en m² ;
- orientation 0–359°, réglable par cadran/boussole et valeur numérique ;
- exposition `AUTO / SUN / SHADE / UNKNOWN` ;
- reconstruction historique : oui/non ;
- zéro, une ou plusieurs sondes extérieures associées.

Raccourcis d'orientation prévus dans l'UI : gauche +90°, droite -90°, opposé +180°, parallèle.

## Deux moteurs d'apprentissage distincts

### Moteur inertiel bâtiment

Entrée cible : une seule sonde intérieure à la fois, comme aujourd'hui.

Il utilise progressivement :

- air intérieur mesuré ;
- référence météo officielle ;
- dalle / états inertiels existants ;
- murs explicites disponibles ;
- masse cachée résiduelle.

Les périodes d'apprentissage peuvent être sélectionnées indépendamment du moteur solaire.

### Moteur solaire / façade

But : apprendre la dynamique locale d'un pan de mur à partir de :

- référence météo officielle ;
- orientation du pan ;
- date / saison ;
- géométrie solaire (azimut + hauteur) ;
- exposition/ombrage appris ;
- inertie propre du pan ;
- vraie sonde extérieure lorsqu'elle existe.

Le déphasage ne doit jamais être un simple offset horaire fixe entre deux murs. Les heures de montée/descente varient avec la saison et la course du soleil.

Une seule bonne journée ensoleillée peut donner une première estimation, mais avec confiance faible. La confiance augmente avec plusieurs journées et saisons.

## Reconstruction des pans

Pour chaque pan, l'utilisateur choisit explicitement s'il souhaite reconstruire l'historique.

- si une vraie mesure existe à un timestamp : elle gagne ;
- sinon une valeur `RECONSTRUCTED` peut être conservée ;
- une meilleure version du modèle peut recalculer les points reconstruits, jamais les vrais points ;
- absence de reconstruction reste un choix valide.

Un pan instrumenté peut fournir une dynamique transférable à un pan similaire. La surface du mur intervient surtout dans son poids énergétique pour le bâtiment ; elle ne doit pas être utilisée naïvement comme multiplicateur direct de température de façade.

## Sélections d'entraînement

Une sélection de données doit proposer :

- Utiliser ;
- Exclure ;
- N'utiliser que cette sélection.

Puis une cible indépendante :

- moteur inertiel ;
- moteur solaire ;
- les deux.

Les fenêtres temporelles des deux moteurs n'ont pas besoin d'être identiques.

## Chaîne cible

Référence météo officielle
→ façades mesurées / reconstruites
→ états thermiques des murs
→ air intérieur + dalle + masse cachée résiduelle

La masse cachée perd progressivement ce que les murs explicités arrivent à expliquer, mais ne disparaît jamais arbitrairement.
