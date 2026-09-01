from pathlib import Path

LAB = Path('app/src/main/java/com/fabdata/app/LyonLabLayer.kt')
text = LAB.read_text(encoding='utf-8')

# Official Package Observations API: 24h / one station / 6-minute observations.
# Current documented public route uses infra-horaire-6m (with hyphen) and no
# explicit API version segment. DPObs v2 remains the official single-point fallback.
text = text.replace(
    'https://public-api.meteofrance.fr/public/DPPaquetObs/v1/paquet/infrahoraire-6m',
    'https://public-api.meteofrance.fr/public/DPPaquetObs/paquet/infra-horaire-6m'
)

LAB.write_text(text, encoding='utf-8')
print('FabData v0.9.0 official Météo-France package route fixed')
