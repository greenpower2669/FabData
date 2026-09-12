# TODO — FabData

## Affichage des références d’apprentissage

- [ ] **Mieux afficher la référence météo liée aux modèles d’apprentissage.**
  - Montrer clairement la référence météo utilisée par le modèle thermique / inertiel et les modèles solaires.
  - Employer partout les libellés UI suivants :
    - **Référence terrain** = réel mesuré prioritaire + reconstruction météo pour combler les trous.
    - **Prévision météo H+24** = prévision Météo-France à échéance fixe H+24.
    - **Prévision Fab H+24** = correction locale Fab de la prévision H+24.
    - **Sol inertiel estimé** = courbe thermique / inertielle, totalement indépendante des prévisions météo.
  - Dans les écrans d’apprentissage, afficher explicitement :
    - **Référence météo du modèle : <nom de la référence active>**
    - **Période météo disponible : <début> → <fin>**
    - après extension d’historique : **Historique météo étendu · réentraînement requis pour en profiter**
    - si la référence active ne correspond plus à celle du modèle : **Référence météo différente · réentraînement requis**
    - si le modèle est cohérent avec la référence courante : **Modèle figé · référence météo inchangée**
  - Indiquer visuellement qu’un **+90 jours d’historique météo enrichit la référence disponible**, mais **ne modifie pas automatiquement un modèle déjà entraîné**.
  - Afficher qu’un **réentraînement manuel** est nécessaire pour que le modèle profite de la nouvelle profondeur historique.
  - Conserver le comportement actuel : modèle figé tant que l’utilisateur ne relance pas explicitement l’entraînement.
  - Si la référence météo active change, rendre l’état **« Référence météo différente · réentraînement requis »** beaucoup plus visible.

## Cadrans météo — mode compact

- [ ] **Permettre de réduire les cadrans en un petit paquet de points circulaires.**
  - Un **double-clic / double-tap sur le cadre des cadrans** bascule entre le mode complet et le mode compact.
  - En mode compact, remplacer les cadrans par un **petit groupe de points circulaires**, suffisamment lisible pour se repérer sans masquer les courbes.
  - Le **cadre et le remplissage du paquet compact** doivent reprendre l’identité visuelle du **cadran PRÉSENT** (même couleur / état visuel principal).
  - Un nouveau double-clic / double-tap restaure les cadrans complets.
  - Mémoriser le choix **compact / complet** comme une personnalisation utilisateur persistante.

## Prévision Fab adaptative — H+3 / H+6 / H+12 / H+24

- [ ] **Construire une prévision Fab adaptative à quatre horizons fixes : H+3, H+6, H+12 et H+24.**
  - Chaque horizon doit disposer de sa propre évaluation et pouvoir être comparé à la **Référence terrain** lorsque l’échéance devient réelle.
  - Exploiter l’historique immuable des prévisions météo déjà archivé afin de mesurer l’erreur propre à chaque horizon.
  - En situation météo normale, utiliser l’apprentissage historique pertinent pour l’horizon concerné.
  - En cas de **changement de régime / météo exceptionnelle**, réduire fortement l’influence d’un passé devenu peu représentatif et privilégier la dynamique récente.
  - Intégrer la logique de **tangente / pente / accélération** du présent comme information de projection, puis apprendre les erreurs habituelles de cette projection selon les situations comparables.
  - Rester strictement causal : une prévision faite à T ne doit utiliser que des informations disponibles à T, sans fuite de données futures.
  - Conserver séparément les résultats H+3, H+6, H+12 et H+24 pour mesurer à quel horizon l’adaptation Fab apporte réellement un gain sur la météo brute.
  - Ne pas modifier les cadrans H+24 actuels tant que cette prévision adaptative multi-horizon n’est pas validée.
