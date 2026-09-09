# FabData v0.20.7 — audit performance et orchestration

Audit lancé après le retour terrain du 9 septembre 2026 : une extension historique semble rester longtemps en « Mise à jour… », l’utilisateur peut réappuyer plusieurs fois sur l’allongement, et il n’existe pas de panneau central permettant de voir/annuler les routines en cours.

## Constats P0

1. **Risque de multi-lancement de l’historique.** `beginNext90DayHistory()` et `beginHistoryWork()` effectuent des lectures suspendues avant que `processNextHistoryChunk()` ne pose `busy = true`. Plusieurs taps rapides peuvent donc lancer plusieurs coroutines avant que l’UI ne se verrouille. Le correctif doit être un garde single-flight pris avant la première suspension, pas uniquement un bouton grisé après coup.

2. **Reload de toute l’UI pendant les écritures par batch.** La reconstruction thermique appelle `onDataChanged()` depuis le callback de progression dès que des points ont été écrits. Le moteur publie cette progression à chaque batch SQLite (256 points). Une tranche de 90 jours peut donc provoquer plusieurs rechargements globaux pendant que la même reconstruction continue à écrire, avec contention DB et impression de blocage. Le progrès doit être affiché sans relire toutes les courbes ; le graphe est rechargé à la fin ou de façon fortement throttlée.

3. **Vue globale météo non décimée.** Les sondes ordinaires sont limitées à ~600 points pour la prévisualisation, mais la référence météo est actuellement relue sur toute la période globale sans limite explicite avant affichage. Plus l’historique grandit, plus ce coût augmente.

## Constats P1

4. **Recomposition de style très fréquente.** `styleTick` évolue toutes les ~180 ms hors calcul thermique. Cette cadence est excessive pour une interface de courbes historiques et augmente le coût de recomposition. Elle doit être ralentie ou activée seulement lorsqu’une animation en a réellement besoin.

5. **Erreurs réseau historiques peu diagnostiques.** Certains appels Open-Meteo sont encapsulés dans `runCatching(...).getOrDefault(emptyList())`. Une erreur fournisseur/réseau peut donc apparaître ensuite comme une simple couverture insuffisante. Le panneau d’activité doit garder la phase, l’heure de départ et le dernier diagnostic.

6. **Le live se déclenche au retour au premier plan.** `FabLiveUpdateCoordinator` lance météo récente + réconciliation + éventuelle prévision au `ON_RESUME`, puis toutes les 5 minutes. Ce comportement est voulu mais peut se superposer visuellement avec une opération manuelle si elles ne partagent pas le même orchestrateur.

## Limites vérifiées

- La prévisualisation propose 6, 12, 24, 36 et 48 mois.
- L’historique thermique est limité à 1464 jours (~48 mois), pas à 24 mois.
- Le bouton d’extension manuelle ajoute au maximum 90 jours à la fois.
- La météo manuelle remonte présent → passé ; la reconstruction thermique intérieure reste passé → présent.

La borne gauche 18/09/2024 visible avec le preset « 24 mois » au 09/09/2026 correspond donc au cadrage choisi et ne prouve pas, à elle seule, une absence de données plus anciennes.

## Plan v0.20.7

- registre central des opérations (nom, démarrage, phase, progression, état, annulation) ;
- bouton ↕ dans la barre supérieure ouvrant « Activité » ;
- annulation coopérative + single-flight pour empêcher les doubles lancements ;
- plus de reload global à chaque batch de 256 points ;
- décimation de la série météo de vue globale ;
- cadence de style réduite ;
- bandeau min/max de la période de prévisualisation : date + minimum à gauche, maximum + date à droite, couleur thermique renforcée jusqu’au violet pour valeurs extrêmes.
