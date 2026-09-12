# TODO — FabData

## Affichage des références d’apprentissage

- [ ] **Mieux afficher la référence météo liée aux modèles d’apprentissage.**
  - Montrer clairement la référence météo utilisée par le modèle thermique / inertiel et les modèles solaires.
  - Indiquer visuellement qu’un **+90 jours d’historique météo enrichit la référence disponible**, mais **ne modifie pas automatiquement un modèle déjà entraîné**.
  - Afficher qu’un **réentraînement manuel** est nécessaire pour que le modèle profite de la nouvelle profondeur historique.
  - Conserver le comportement actuel : modèle figé tant que l’utilisateur ne relance pas explicitement l’entraînement.
  - Si la référence météo active change, rendre l’état **« référence différente · réentraînement requis »** beaucoup plus visible.

