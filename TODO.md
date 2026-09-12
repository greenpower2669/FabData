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
