# Publication Google Play — FabData v0.7

Ce document décrit le flux de publication **sans PC** : GitHub Actions produit l'APK et l'Android App Bundle `.aab`, puis la Play Console est utilisée depuis le navigateur du téléphone.

## Identité Android

- applicationId : `com.fabdata.app`
- versionCode : `7`
- versionName : `0.7`
- minSdk : `26`
- targetSdk : `36`
- compileSdk : `36`

L'`applicationId` ne doit plus être changé après la première publication sur Google Play.

## Fichiers produits

Le workflow `.github/workflows/android-build.yml` construit :

- `artifacts/FabData-v0.7-release.apk` — installation directe / tests ;
- `artifacts/FabData-v0.7-release.aab` — Android App Bundle ;
- `artifacts/FabData-v0.7-signing-mode.txt` — indique la clé utilisée par le build.

## Signature Google Play

Le build sait utiliser une clé d'import Google Play permanente à partir de secrets GitHub.

Secrets attendus :

- `FABDATA_UPLOAD_KEYSTORE_BASE64`
- `FABDATA_UPLOAD_STORE_PASSWORD`
- `FABDATA_UPLOAD_KEY_ALIAS`
- `FABDATA_UPLOAD_KEY_PASSWORD`

La clé privée ne doit jamais être ajoutée au dépôt Git public.

Si ces quatre secrets ne sont pas présents, GitHub Actions utilise volontairement une signature de développement de secours afin de continuer à produire des fichiers testables. Dans ce cas, `FabData-v0.7-signing-mode.txt` contient `development-fallback` et l'AAB ne doit pas être considéré comme le bundle définitif de publication.

Quand les quatre secrets sont configurés, le fichier contient `google-play-upload-key`.

### Certificat public de la clé d'import FabData

Alias : `fabdata-upload`

SHA-256 :

```text
E1:D3:A5:19:04:9A:2D:91:45:60:D7:0E:C7:DF:3F:2E:C4:E0:EA:FF:5F:FA:E4:FE:22:83:E9:89:7C:C7:67:22
```

SHA-1 :

```text
B9:5F:B8:A9:A6:8A:3D:A5:25:FA:2F:37:88:38:45:AA:DD:5C:88:08
```

Validité du certificat : jusqu'au 27 juin 2059.

Ces empreintes sont publiques et peuvent être comparées à celles affichées dans la Play Console. Le keystore privé et ses mots de passe restent hors du dépôt.

## Ajouter les secrets depuis un téléphone

Dans le navigateur du téléphone :

1. ouvrir le dépôt GitHub FabData ;
2. `Settings` ;
3. `Secrets and variables` ;
4. `Actions` ;
5. créer chacun des quatre secrets ci-dessus ;
6. relancer le workflow Android APK + AAB.

Pour `FABDATA_UPLOAD_KEYSTORE_BASE64`, coller la représentation Base64 complète du keystore d'import.

## Première publication dans Play Console

1. Ouvrir la Google Play Console dans Chrome sur Android. Le mode « Site pour ordinateur » peut rendre certaines pages plus pratiques.
2. Créer une nouvelle application nommée **FabData**.
3. Choisir la langue principale et le type « Application ».
4. Compléter les informations requises dans `Contenu de l'application`.
5. Ajouter la politique de confidentialité publique correspondant à `PRIVACY_POLICY.md`.
6. Compléter le questionnaire de classification du contenu.
7. Compléter la section `Sécurité des données`.
8. Préparer la fiche Play Store : nom, description courte, description complète, icône et captures d'écran.
9. Commencer par une release de **test interne**.
10. Importer le `.aab` signé avec la clé d'import Google Play.
11. Activer / accepter **Play App Signing** pour la nouvelle application.
12. Corriger les éventuels avertissements de la Play Console avant d'élargir la diffusion.

## Déclaration Sécurité des données — état actuel du code

Pour la version v0.7 actuelle :

- aucune donnée utilisateur envoyée à un serveur FabData ;
- aucune donnée vendue ou partagée par l'application ;
- pas de compte utilisateur ;
- pas de publicité ;
- pas d'analytique ;
- pas de permission Internet ;
- pas de localisation, caméra, microphone, contacts ou journaux d'appels ;
- données thermo-hygrométriques et annotations conservées localement ;
- imports/exports déclenchés explicitement par l'utilisateur via le sélecteur de fichiers Android.

La déclaration Play Console doit être revue à chaque ajout futur d'un SDK, d'une synchronisation cloud, d'une connexion réseau ou d'un autre traitement de données.

## Mises à jour futures

Pour chaque nouvelle version publiée :

1. incrémenter obligatoirement `versionCode` ;
2. mettre à jour `versionName` ;
3. conserver exactement `applicationId = com.fabdata.app` ;
4. conserver la même clé d'import, sauf procédure officielle de réinitialisation dans Play Console ;
5. produire et envoyer le nouvel `.aab`.

La clé de signature finale distribuée aux utilisateurs est gérée par Play App Signing. Le keystore FabData est la **clé d'import**, utilisée pour authentifier les bundles envoyés à Google Play.
