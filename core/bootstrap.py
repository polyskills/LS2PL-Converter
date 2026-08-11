"""
Données par défaut recréées automatiquement à chaque démarrage de l'app.

Sur Streamlit Community Cloud, le disque n'est pas persistant d'un
redéploiement/redémarrage à l'autre, et data/clients/ n'est volontairement
pas versionné dans git (données clients sensibles). Sans ce mécanisme, les
clients, points de vente et référentiel de départ créés uniquement via
l'interface disparaîtraient au premier reboot.

Ce module réinjecte, de façon idempotente (jamais de doublon, jamais
d'écrasement d'une personnalisation existante), les données qui doivent
survivre à un redémarrage. Toute donnée saisie ensuite dans l'interface
(comptes, codes analytiques...) reste, elle, soumise à la persistance
disque habituelle.
"""
from __future__ import annotations

from core.client_store import ensure_client
from core.mapping_store import (
    ensure_comptes_de_vente,
    ensure_comptes_paiement,
    ensure_comptes_tva,
    ensure_departements,
    ensure_points_de_vente,
    set_pdv_adresse_email,
)

DEFAULT_CLIENTS = [
    {"id": "paris", "nom": "Paris"},
    {"id": "valence", "nom": "Valence"},
]

DEFAULT_POINTS_DE_VENTE = [
    {"code": "RESTAURANT", "libelle": "RESTAURANT"},
    {"code": "BAR", "libelle": "BAR"},
]

# Adresses mail dédiées à la réception automatique des exports LightSpeed,
# une par point de vente (cf. échange avec le client, août 2026). Ne
# concernent que le site Paris pour l'instant ; Valence n'a pas encore
# d'adresse dédiée, le champ y reste vide jusqu'à confirmation.
DEFAULT_ADRESSES_EMAIL = {
    "paris": {
        "RESTAURANT": "rapport_ls_paris_restaurant@annesophiepic-paris.com",
        "BAR": "rapport_ls_paris_bar@annesophiepic-paris.com",
    },
}

# Référentiel réel transmis par le client (août 2026) pour le site Paris.
# Les comptes de vente par département, les comptes de TVA collectée et les
# comptes de contrepartie de paiement restent volontairement vides
# ("compte": "") : seuls le département/le taux (ou le mode de paiement/le
# taux) sont confirmés à ce stade, le compte exact reste à choisir par le
# client dans l'interface (liste déroulante restreinte à ce référentiel).
# Tant qu'un compte est vide, la conversion bloque sur ce point plutôt que
# de deviner - volontaire, cf. philosophie générale de l'outil.
DEFAULT_COMPTES_DE_VENTE = {
    "paris": [
        {"compte": "75810020", "libelle_compte": "FRAIS D'ANNULATION TVA 20 %"},
        {"compte": "75800000", "libelle_compte": "PRODUITS DIV. GESTION COURANTE"},
        {"compte": "70859000", "libelle_compte": "PRODUITS/SERVICES ACCESSOIRES EXO"},
        {"compte": "70850050", "libelle_compte": "PRODUITS/SERVICES ACCESSOIRES TVA 5"},
        {"compte": "70850029", "libelle_compte": "PRODUITS/SERVICES GROUP TVA 20%"},
        {"compte": "70850020", "libelle_compte": "PRODUITS/SERVICES ACCESSOIRES TVA 2"},
        {"compte": "70715000", "libelle_compte": "VENTES TVA 5,5%"},
        {"compte": "70712200", "libelle_compte": "VENTES TVA 20%"},
        {"compte": "70712001", "libelle_compte": "VENTES FRAIS D ENVOI"},
        {"compte": "70710001", "libelle_compte": "VENTES DIVERSES EXO. (CIGARES)"},
        {"compte": "70112500", "libelle_compte": "VENTE SECRET BOX TVA 5,5%"},
        {"compte": "70112220", "libelle_compte": "VENTE CHEQUE CADEAUX 20%"},
        {"compte": "70112200", "libelle_compte": "VENTE SECRET BOX TVA 20%"},
        {"compte": "70112100", "libelle_compte": "VENTE SECRET BOX TVA 10%"},
        {"compte": "70110200", "libelle_compte": "VENTE LIQUIDE TVA 20%"},
        {"compte": "70110100", "libelle_compte": "VENTE LIQUIDE  TVA 10%"},
        {"compte": "70110010", "libelle_compte": "VENTES SOLIDE TVA 10%"},
    ],
}

DEFAULT_DEPARTEMENTS = {
    "paris": [
        {"categorie_lightspeed": "Autres Spiritueux", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Bière", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Boisson Chaude", "compte": "", "taux_tva": "10%"},
        {"categorie_lightspeed": "Boisson Froide", "compte": "", "taux_tva": "10%"},
        {"categorie_lightspeed": "Cidre, Poiré, Hydromel", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Cocktail", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Cuisine", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Divers 10%", "compte": "", "taux_tva": "10%"},
        {"categorie_lightspeed": "Divers 20%", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Liqueur", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Menu", "compte": "", "taux_tva": "10%"},
        {"categorie_lightspeed": "Rhum", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Saké", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin Blanc", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin Effervescent", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin Liquoreux", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin Orange", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin Rosé", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vin Rouge", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Vins au verre", "compte": "", "taux_tva": "20%"},
        {"categorie_lightspeed": "Whisky", "compte": "", "taux_tva": "20%"},
    ],
}

DEFAULT_COMPTES_PAIEMENT = {
    "paris": [
        {"mode_paiement": "VISA / MASTERCARD", "compte": ""},
        {"mode_paiement": "ESPECE", "compte": ""},
        {"mode_paiement": "SECRET BOX", "compte": ""},
        {"mode_paiement": "FACTURE", "compte": ""},
    ],
}

DEFAULT_COMPTES_TVA = {
    "paris": [
        {"taux": "20%", "compte": ""},
        {"taux": "10%", "compte": ""},
        {"taux": "5.5%", "compte": ""},
    ],
}


def ensure_defaults() -> None:
    for c in DEFAULT_CLIENTS:
        ensure_client(c["id"], c["nom"])
        ensure_points_de_vente(c["id"], DEFAULT_POINTS_DE_VENTE)
        for code_pdv, adresse in DEFAULT_ADRESSES_EMAIL.get(c["id"], {}).items():
            set_pdv_adresse_email(c["id"], code_pdv, adresse)
        ensure_comptes_de_vente(c["id"], DEFAULT_COMPTES_DE_VENTE.get(c["id"], []))
        ensure_departements(c["id"], DEFAULT_DEPARTEMENTS.get(c["id"], []))
        ensure_comptes_paiement(c["id"], DEFAULT_COMPTES_PAIEMENT.get(c["id"], []))
        ensure_comptes_tva(c["id"], DEFAULT_COMPTES_TVA.get(c["id"], []))
