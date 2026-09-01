# FABDATA — LYON : 3 SOURCES, RECONSTRUCTION, JOURNAL ET PERSONNALISATION

Statut : spécification validée à embarquer lors du prochain run de développement.

IMPORTANT : ce document ne demande aucune réécriture destructive des données existantes. Les données brutes doivent rester consultables et intactes.

## 1. Trois vues Lyon indépendantes

Le détail de la sonde Lyon doit proposer un sélecteur compact à 3 états, parcouru par un clic/tap :

1. `6 min officiel`
2. `Horaire officiel`
3. `Reconstruit`

Un tap sur le sélecteur passe à l’état suivant. Prévoir aussi un libellé clair de la source active.

### 6 min officiel

- observations temps réel Météo-France Lyon-Bron 69029001 ;
- pas nominal 6 minutes ;
- conservation locale définitive des points déjà acquis ;
- pas d’interpolation stockée comme donnée brute ;
- un point officiel suspect reste consultable dans cette vue même si la reconstruction décide de ne pas l’utiliser.

### Horaire officiel

- archive climatologique Météo-France Lyon-Bron 69029001 ;
- température/humidité horaires qualifiées ;
- sert de référence historique et de contrôle des incohérences du 6 min ;
- ne remplace jamais des points 6 min sains dans les données brutes.

### Reconstruit

- série de travail/d’affichage construite à partir des deux séries officielles ;
- jamais présentée comme une observation brute ;
- corrigeable manuellement ;
- chaque décision doit être traçable dans le journal.

## 2. Reconstruction tangentielle / continuité

Objectif : produire une courbe physiquement cohérente sans masquer l’origine des données.

Principes :

- utiliser en priorité le 6 min officiel sain ;
- utiliser l’horaire officiel comme ancre de contrôle et comme base lorsque le 6 min est absent ou manifestement incohérent ;
- entre deux ancres fiables, reconstruire une continuité en suivant la tendance locale (tangente), avec interpolation douce et sans oscillations artificielles ;
- éviter les sur-oscillations : préférer une interpolation monotone / Hermite bornée plutôt qu’un spline libre ;
- borner les pentes physiquement aberrantes ;
- ne jamais modifier les tables brutes pour rendre la courbe plus jolie.

Un exemple du type `27.8 -> 17.2 -> 27.4 °C` en quelques minutes doit être classé suspect, comparé aux voisins et à l’horaire officiel, puis éventuellement exclu de la courbe reconstruite.

## 3. Décisions de reconstruction

Pour chaque point ou segment où la courbe reconstruite diffère de la donnée brute, conserver :

- timestamp ;
- valeur 6 min officielle éventuelle ;
- valeur horaire officielle éventuelle ;
- valeur reconstruite choisie ;
- origine de la décision : automatique ou manuelle ;
- état : conservé / rejeté comme suspect / interpolé / corrigé manuellement ;
- date de modification.

### Raisonnement très court

Chaque décision automatique possède une explication de **2 lignes maximum**.

Exemples :

`Point 6 min écarté : -10.1 °C par rapport aux voisins.`
`Horaire officiel et tangente locale concordent.`

ou :

`Aucune observation 6 min sur ce créneau.`
`Interpolation entre deux ancres horaires fiables.`

Pas de longs textes générés dans ce journal.

## 4. Journal Lyon détaillé

Dans `Détail Lyon`, afficher un journal précis, chronologique et filtrable autour de la période visible.

Chaque entrée montre au minimum :

- date/heure ;
- source(s) concernée(s) ;
- valeur(s) ;
- décision ;
- raisonnement <= 2 lignes ;
- badge `AUTO` ou `MANUEL`.

Le journal doit permettre de comprendre pourquoi la courbe reconstruite monte, descend, ignore un point ou comble un trou.

## 5. Correction manuelle par double-tap

Dans la vue `Reconstruit` :

- simple tap = sélectionner/inspecter ;
- double-tap sur un point/instant = ouvrir l’éditeur de correction ;
- l’utilisateur peut modifier température et, si disponible, humidité ;
- possibilité d’ajouter une petite note facultative ;
- la correction est stockée comme **override manuel**, séparée des données officielles ;
- le journal ajoute une entrée `MANUEL` ;
- prévoir `Revenir à Auto` pour supprimer l’override et recalculer le point.

Les vues `6 min officiel` et `Horaire officiel` restent non destructives : elles affichent les valeurs officielles telles qu’elles ont été reçues.

## 6. Valeurs et priorités de la courbe reconstruite

Ordre de décision recommandé :

1. override manuel ;
2. point 6 min officiel validé ;
3. point/ancres horaires officiels ;
4. interpolation tangentielle entre ancres fiables ;
5. trou si aucune reconstruction raisonnable n’est possible.

Une reconstruction ne doit pas s’étendre arbitrairement sur un grand trou sans ancres fiables.

## 7. Contrôle d’incohérence

Un point 6 min peut être marqué suspect lorsqu’il combine plusieurs signaux, par exemple :

- excursion brutale puis retour immédiat ;
- écart important par rapport à la tendance des voisins ;
- contradiction forte avec l’horaire officiel ;
- dérivée/pente incompatible avec les points adjacents ;
- donnée hors bornes plausibles.

Ne pas éliminer une vraie variation météo sur un seul critère : utiliser plusieurs indices et conserver toujours le brut consultable.

## 8. Personnalisation individuelle des courbes

Réintégrer la personnalisation prévue dans le checkpoint EVO. Elle s’applique **par courbe / par sonde**, pas comme thème global.

Chaque courbe dispose de :

1. `Style A`
2. `Style B`
3. `Aura A`
4. `Aura B`
5. `Opacité`

### Styles

Choix extensibles :

- couleurs fixes ;
- couleur personnalisée ;
- Arc-en-ciel ;
- Iridescence ;
- futurs effets animés ;
- `Pas de couleur`.

Si Style A = Style B : pas d’alternance A/B, mais l’effet interne d’un style animé continue.

Si Style A != Style B : alternance cyclique.

`Pas de couleur` est un véritable état et permet par exemple : Rouge -> invisible -> Rouge.

### Auras

Choix initiaux :

- Pas d’aura ;
- Soleil ;
- Ombre ;
- Glace ;
- Nature.

Aura A/B alternent indépendamment de Style A/B.

### Opacité

- 0 à 100 % ;
- indépendante du style et de `Pas de couleur`.

### Sélecteurs

Style A/B et Aura A/B : tourniquet compact, par exemple `‹ Arc-en-ciel ›`.

Opacité : slider + valeur numérique.

## 9. Personnalisation spécifique des trois courbes Lyon

Dans `Détail Lyon`, permettre des identités visuelles différentes pour :

- 6 min officiel ;
- horaire officiel ;
- reconstruit.

Cela permet de les comparer sans ambiguïté. Les réglages doivent être conservés entre les lancements.

## 10. Intégrité / stockage

Architecture souhaitée lors de l’implémentation :

- conserver `samples` existant sans réécriture destructive ;
- stocker les futures séries officielles Lyon avec leur origine explicite ;
- stocker les overrides manuels séparément ;
- stocker ou recalculer les décisions automatiques avec journal déterministe ;
- migration SQLite transactionnelle et additive uniquement ;
- ne jamais écraser une observation officielle par une reconstruction ;
- sauvegarde/export des nouveaux objets à traiter dans une évolution dédiée du format de backup, pas silencieusement.

## 11. Sources Météo-France retenues

Station principale : Lyon-Bron `69029001`.

- temps réel température/humidité : API Observations, pas 6 minutes, profondeur 24 h ;
- historique température/humidité : API Climatologie, pas horaire, historique qualifié ;
- les archives climatologiques 6 minutes ne doivent pas être utilisées pour reconstruire température/humidité : ce produit est destiné à la précipitation.

Infoclimat devient une source de diagnostic/secours, pas la référence pour écrire la courbe officielle Lyon.

## 12. Séquence d’implémentation recommandée

1. stockage multi-source Lyon + migration additive ;
2. client Météo-France officiel et gestion du token ;
3. récupération 6 min des dernières 24 h ;
4. récupération horaire historique ;
5. détail Lyon avec sélecteur 3 états ;
6. moteur de reconstruction tangentielle + journal 2 lignes ;
7. overrides manuels par double-tap + Revenir à Auto ;
8. personnalisation Style A/B, Aura A/B, Opacité ;
9. appliquer les styles au graphe principal et au détail Lyon ;
10. seulement après validation : évolution du backup pour inclure sources/overrides/styles sans casser le format existant.
