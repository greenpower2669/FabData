# CHECKPOINT FABDATA EVO — REPRISE 31 AOÛT 2026

## Statut

EN ATTENTE jusqu’à la reprise du 31/08/2026.

La version actuelle de FabData reste la base stable. Ne pas considérer les fonctions ci-dessous comme déjà implémentées.

La reprise doit commencer par la sécurité et l’intégrité des données avant toute évolution graphique.

---

# 0 — PRIORITÉ ABSOLUE : INTÉGRITÉ / ZÉRO PERTE

Bug constaté visuellement :

- certaines anciennes annotations ne sont plus visibles ;
- certaines anciennes portions de courbes semblent absentes ou corrompues ;
- descendre complètement dans la page ne permet pas de retrouver les anciennes annotations ;
- une ancienne « partie 2 » de certaines données semble absente.

Hypothèse principale retenue à vérifier en premier : **les données et annotations sont probablement encore présentes dans SQLite mais sont exclues de l’affichage par le fenêtrage temporel actuel.**

Avant toute modification :

1. Faire une sauvegarde FabData complète de la base existante.
2. Auditer SQLite.
3. Pour chaque sonde relever :
   - id interne ;
   - stableKey ;
   - nom ;
   - pièce ;
   - nombre total de mesures ;
   - première date stockée ;
   - dernière date stockée ;
   - nombre total d’annotations associées.
4. Relever également :
   - nombre total de sondes ;
   - nombre total de mesures ;
   - nombre total d’annotations ;
   - première date de toute la base ;
   - dernière date de toute la base.
5. Comparer ces bornes avec la fenêtre actuellement affichée.
6. Vérifier spécifiquement les anciennes annotations et la « partie 2 » des courbes.
7. Ne rien supprimer, fusionner ou réécrire avant ce diagnostic.

Règle : **historique stocké et fenêtre affichée sont deux choses différentes.**

---

# 1 — PROTECTION DES MIGRATIONS

Avant toute future migration importante :

- sauvegarde/snapshot préalable ;
- migration transactionnelle ;
- comptage mesures/annotations avant et après ;
- rollback en cas d’incohérence.

Interdictions :

- pas de drop/recreate silencieux ;
- pas de migration destructive ;
- pas de remplacement automatique par une base vide ;
- pas de suppression automatique pour « réparer ».

---

# 2 — HISTORIQUE COMPLET ET FENÊTRE AFFICHÉE

Afficher clairement deux informations distinctes :

- **Historique stocké** : période réellement présente dans SQLite ;
- **Fenêtre affichée** : période actuellement visible dans le graphe principal.

Exemple :

- Historique stocké : 18/08 → 29/08
- Fenêtre affichée : 27/08 → 29/08

Une donnée hors fenêtre ne doit jamais donner l’impression d’avoir été supprimée.

Ajouter une commande :

- `Tout l’historique`
- ou `Ajuster à toutes les données`

pour vérifier immédiatement la présence des données stockées.

---

# 3 — ANNOTATIONS : PÉRIODE VS TOUTES

La liste des annotations située sous le graphe ne doit plus dépendre obligatoirement de la fenêtre du graphe.

Prévoir :

- `Annotations de la période`
- `Toutes les annotations`

Une annotation ancienne doit rester retrouvable même si le graphe principal n’affiche que 48 h.

---

# 4 — FORMAT / IMPORT TEMPOREL À CORRIGER

Le format thermo reconnu ne doit plus reconstruire artificiellement toute la série à partir de la première ligne avec un pas fixe de 60 secondes.

Correction souhaitée :

- utiliser le timestamp réellement présent dans CHAQUE ligne dès qu’il est valide ;
- conserver les trous réels ;
- conserver les coupures ;
- conserver les intervalles irréguliers ;
- conserver les blocs discontinus ;
- ne jamais inventer une continuité temporelle.

Le pas artificiel de 60 secondes ne peut servir qu’en secours très encadré si la source ne fournit réellement aucun timestamp exploitable.

---

# 5 — IDENTITÉ DES SONDES

Surveiller le cas où le même thermomètre importé sous des noms de fichier différents crée plusieurs stableKey et sépare artificiellement l’historique.

Détecter les cas probables, mais :

- ne jamais fusionner automatiquement ;
- proposer une fusion contrôlée seulement après diagnostic ;
- préserver les données originales jusqu’à validation.

---

# 6 — TROUS ET SEGMENTS DE COURBE

Distinguer explicitement :

- donnée réellement absente ;
- donnée hors fenêtre ;
- donnée invalide ;
- segment attaché à une autre sonde ;
- segment non rendu ;
- donnée réellement supprimée.

Une partie 1 et une partie 2 séparées temporellement doivent rester aux bonnes dates.

---

# 7 — ZOOM TEMPOREL PRINCIPAL

Ajouter les périodes :

- 1 h
- 24 h
- 48 h
- 1 semaine
- 1 mois

Valeur présélectionnée par défaut : **48 h**.

Mais ce choix reste modifiable.

Présentation souhaitée :

`1 h   24 h   [48 h]   1 sem.   1 mois`

Une seule durée active à la fois.

Le bouton actif doit paraître enfoncé/sélectionné.

---

# 8 — SÉLECTION INITIALE AU MILIEU

Au démarrage du graphe principal, initialiser un timestamp valide au milieu de la fenêtre visible :

`selectedTimestamp = start + (end - start) / 2`

Objectifs :

- éviter les états null fragiles ;
- fiabiliser le premier affichage ;
- simplifier curseur, inspection et valeurs hors échelle ;
- éviter les bugs au premier geste.

La sélection initiale peut rester visuellement discrète.

---

# 9 — GESTES DU GRAPHE

Nouvelle logique :

- clic simple / tap : sélectionner / déplacer le curseur / inspecter ;
- double-clic / double-tap : créer un événement ou une annotation à cet instant ;
- appui long : zoom rapide autour de la zone touchée.

L’appui long utilise la durée de zoom actuellement sélectionnée.

Bien empêcher les doubles déclenchements entre simple tap, double tap et appui long.

---

# 10 — MINI-VUE GLOBALE DE NAVIGATION TEMPORELLE

Ajouter une **petite barre graphique compacte** représentant l’ensemble de l’historique disponible.

IMPORTANT : ce n’est PAS une nouvelle page et ce n’est PAS un deuxième écran d’analyse.

C’est une mini-vue toujours intégrée à proximité du graphe principal, servant uniquement de navigateur temporel.

Elle doit :

- représenter toute la période réellement stockée ;
- rester très compacte ;
- montrer une version simplifiée/minimisée des courbes ;
- ne jamais être limitée à la fenêtre déjà chargée dans le graphe principal ;
- rester alimentée par les bornes complètes de l’historique.

## Interaction

Un tap/clic sur un point de cette mini-vue ne crée aucune page.

Il redéfinit directement les bornes `start/end` du **graphe principal**.

Par défaut, lors d’un tap à l’instant `T` :

- `start = T - 24 h`
- `end = T + 24 h`

Donc le graphe principal affiche **48 h centrées sur le point choisi**.

Exemple :

si l’utilisateur tape sur un point situé 6 jours plus tôt, le graphe principal se repositionne immédiatement 6 jours plus tôt et affiche les 48 h autour de ce point.

Près du début ou de la fin de l’historique, recalculer proprement la fenêtre afin de conserver 48 h autant que possible sans sortir des bornes disponibles.

## Retour visuel

La mini-vue doit afficher une petite zone/surbrillance indiquant quelles 48 h sont actuellement visibles dans le graphe principal.

À terme, cette zone pourra éventuellement être glissable, mais ce n’est pas obligatoire pour la première implémentation.

Règle : **un seul graphe principal ; la mini-vue ne fait que piloter son start/end.**

---

# 11 — ÉCHELLE VERTICALE

Permettre de choisir quelle famille de données sert de référence pour le min/max Y :

- Station météo / extérieur
- Sonde personnelle / thermomètre

Une seule référence active à la fois.

Ce réglage modifie uniquement le cadrage vertical, jamais les données.

---

# 12 — COURBE HORS CADRE : PAS D’INFO AUTOMATIQUE

Lorsqu’une courbe quitte le haut ou le bas du graphe :

- ne rien afficher automatiquement ;
- pas d’étiquette permanente ;
- pas de chiffre au point de sortie ;
- pas de marqueur parasite.

Objectif : éviter surcharge, collisions et bugs.

---

# 13 — VALEUR HORS ÉCHELLE UNIQUEMENT À LA SÉLECTION

Lorsqu’un instant est sélectionné :

- si la valeur est dans l’échelle : affichage normal ;
- si elle dépasse le max Y : petite valeur au bord supérieur au X du curseur ;
- si elle est sous le min Y : petite valeur au bord inférieur au X du curseur.

Exemple :

sélection = 14:32
vraie valeur = 36,8 °C
max visible = 32 °C

Afficher `36,8°` au bord haut, uniquement au niveau de la sélection.

Aucune indication hors échelle ailleurs.

---

# 14 — ÉTIQUETTES INTÉRIEURES POUR LES COURBES VISIBLES

À l’instant sélectionné, chaque courbe visible peut afficher une petite étiquette de valeur.

L’étiquette doit être placée automatiquement dans une zone vide du graphe plutôt que directement sur la ligne.

Le placement doit essayer d’éviter :

- autres courbes ;
- autres étiquettes ;
- annotations ;
- axes ;
- bords ;
- textes déjà présents.

---

# 15 — FIL DE LIAISON

Chaque étiquette intérieure possède un petit fil très fin reliant l’étiquette au point exact où la verticale de sélection traverse la courbe.

Le fil doit être discret et reprendre l’identité visuelle de la courbe.

---

# 16 — ÉTIQUETTES DÉPLAÇABLES

Chaque étiquette intérieure doit pouvoir être déplacée au doigt.

Le placement automatique est seulement le placement initial.

Si l’utilisateur déplace l’étiquette :

- garder le fil relié au point réel ;
- respecter la position choisie tant qu’elle reste pertinente.

Prévoir éventuellement plus tard un bouton `Auto` / `Replacer automatiquement`.

---

# 17 — AFFICHER / MASQUER LES ÉTIQUETTES INTÉRIEURES

Ajouter un réglage :

`Étiquettes intérieures : ON / OFF`

ON : étiquettes + fils.

OFF : graphe épuré.

Les indications indispensables hors échelle au point sélectionné restent gérées séparément.

---

# 18 — PERSONNALISATION INDIVIDUELLE DES COURBES

Tous les effets suivants appartiennent à chaque courbe individuellement.

Jamais de thème global imposé à toutes les sondes.

Chaque courbe possède 5 lignes de personnalisation :

1. Style A
2. Style B
3. Aura A
4. Aura B
5. Opacité

---

# 19 — STYLE A / STYLE B

Chaque style peut être :

- une couleur fixe ;
- une couleur personnalisée ;
- Arc-en-ciel ;
- Iridescence ;
- un futur effet animé ;
- `Pas de couleur`.

Si Style A = Style B : pas d’alternance A/B supplémentaire.

Si Style A != Style B : alternance cyclique entre les deux.

---

# 20 — PAS DE COULEUR

`Pas de couleur` est une vraie valeur sélectionnable.

Exemple :

Style A = Rouge
Style B = Pas de couleur

Résultat :

Rouge → invisible → Rouge → invisible.

Cela permet naturellement un clignotement/respiration.

---

# 21 — ARC-EN-CIEL ET EFFETS INTERNES

L’Arc-en-ciel possède sa propre animation interne :

rouge → orange → jaune → vert → cyan → bleu → violet → rouge → etc.

Donc Style A = Arc-en-ciel et Style B = Arc-en-ciel reste animé même sans alternance A/B.

---

# 22 — AURA A / AURA B

Premiers choix :

- Pas d’aura
- Aura Soleil
- Aura Ombre
- Aura Glace
- Aura Nature

Catalogue extensible.

Si Aura A != Aura B : alternance cyclique.

Exemple :

Aura A = Glace
Aura B = Pas d’aura

Résultat :

Glace → aucune aura → Glace → aucune aura.

---

# 23 — STYLE ET AURA INDÉPENDANTS

Les cycles Style A/B et Aura A/B sont indépendants.

Exemple :

Style A = Arc-en-ciel
Style B = Iridescence jaune
Aura A = Glace
Aura B = Soleil

La ligne peut alterner Arc-en-ciel ↔ Iridescence pendant que l’aura alterne Glace ↔ Soleil.

---

# 24 — OPACITÉ

Cinquième ligne :

`Opacité : 0 % → 100 %`

L’opacité est indépendante de `Pas de couleur`.

Exemple :

Style A = Rouge
Style B = Pas de couleur
Opacité = 70 %

Résultat :

Rouge à 70 % → invisible → Rouge à 70 % → invisible.

---

# 25 — TOURniquets / CARROUSELS

Pour Style A, Style B, Aura A et Aura B, utiliser des sélecteurs compacts façon tourniquet :

`‹ Arc-en-ciel ›`

`‹ Pas de couleur ›`

`‹ Aura Glace ›`

`‹ Pas d’aura ›`

L’opacité utilise plutôt slider + valeur numérique.

---

# 26 — COULEURS ET EFFETS FUTURS

Augmenter fortement le choix de couleurs.

Prévoir ensuite :

- couleur personnalisée ;
- iridescence jaune ;
- iridescence bleue ;
- dégradés animés ;
- pulsations ;
- transitions douces ;
- respiration ;
- clignotement ;
- vitesse du cycle Style ;
- vitesse du cycle Aura ;
- intensité Aura ;
- largeur Aura ;
- épaisseur de ligne.

Architecture extensible sans refaire le moteur à chaque nouvel effet.

---

# 27 — LISIBILITÉ

Les données restent prioritaires.

Toujours préserver :

- courbe centrale lisible ;
- curseur visible ;
- valeurs précises ;
- étiquettes lisibles ;
- fils très fins ;
- auras non envahissantes ;
- distinction nette entre sondes.

---

# 28 — FONCTIONS ACTUELLES À CONSERVER

Ne pas casser :

- imports thermomètres ;
- historique ;
- température ;
- humidité ;
- annotations ;
- événements ;
- sauvegarde/restauration ;
- Lyon par défaut ;
- possibilité future de remplacer/supprimer Lyon ;
- sondes HTTP ;
- synchronisation automatique ;
- fonction `《 Compléter 》` ;
- complément météo limité à la période réellement couverte par les thermomètres ;
- format de sauvegarde FabData actuel.

---

# 29 — ORDRE DE REPRISE AU 31 AOÛT

0. Sauvegarder la base actuelle.
1. Auditer SQLite et confirmer/infirmer l’hypothèse 1.
2. Vérifier comptes mesures/annotations et bornes temporelles.
3. Corriger le fenêtrage qui masque les anciennes données.
4. Séparer historique stocké et fenêtre affichée.
5. Ajouter `Toutes les annotations` et `Tout l’historique`.
6. Corriger l’import pour respecter chaque timestamp réel.
7. Vérifier les stableKey et historiques éventuellement séparés.
8. Ajouter la mini-vue globale pilotant directement start/end du graphe principal.
9. Ajouter zoom 1 h / 24 h / 48 h / semaine / mois.
10. Initialiser la sélection au milieu.
11. Refaire les gestes : simple / double / long.
12. Ajouter l’échelle verticale météo / sonde personnelle.
13. Ajouter valeurs hors échelle uniquement au curseur.
14. Ajouter les étiquettes intérieures intelligentes.
15. Ajouter fils de liaison et déplacement manuel.
16. Ajouter ON/OFF étiquettes intérieures.
17. Étendre la palette.
18. Style A / Style B / Pas de couleur.
19. Aura A / Aura B / Pas d’aura.
20. Opacité.
21. Tourniquets.
22. Animations avancées.

---

# RÈGLES D’OR

1. **Une donnée stockée ne doit jamais sembler perdue simplement parce qu’elle est hors fenêtre.**
2. **La mini-vue globale ne crée aucune nouvelle page : elle redéfinit uniquement le start/end du graphe principal.**
3. **Un tap sur la mini-vue ouvre par défaut 48 h autour du point choisi.**
4. **Ne jamais inventer de continuité temporelle lorsqu’un trou réel existe dans les données.**
5. **Aucune migration destructive sans sauvegarde et vérification.**

---

## Statut final

Checkpoint complet en attente pour la reprise du 31 août 2026.
