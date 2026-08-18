"""
Point d'entrée du service de fetch automatique des exports LightSpeed.

Boucle infinie : un cycle (core.email_poller.executer_un_cycle) toutes les
`LSPENNYLANE_POLL_INTERVAL_SECONDS` secondes (300 par défaut). Prévu pour
tourner comme second service, indépendant de l'app Streamlit
(voir deploy/windows ou deploy/macos selon l'OS d'hébergement).

L'ID d'application et le secret client Azure AD peuvent être renseignés soit
par client (page Réglages > Gestion Email, prioritaire — recommandé depuis
qu'une app Azure AD est créée par client, cf.
docs/configuration_m365_client.md), soit via les variables d'environnement
ci-dessous, utilisées en repli pour tout client sans identifiants propres
(comportement historique, ne fonctionne que tant qu'un seul client les
utilise sur ce serveur) :
- LSPENNYLANE_AZURE_CLIENT_ID
- LSPENNYLANE_AZURE_CLIENT_SECRET
Aucune des deux n'est donc strictement requise au démarrage du service :
un client sans identifiant disponible (ni propre, ni en repli) est
simplement ignoré à chaque cycle (log d'avertissement), sans bloquer les
autres.

Optionnelle :
- LSPENNYLANE_ALERTE_INTERNE      : adresse mail recevant les alertes et les
                                     récapitulatifs de conversion (aucun envoi
                                     si absente)
- LSPENNYLANE_POLL_INTERVAL_SECONDS : intervalle entre deux cycles (défaut 300)

Le tenant et la boîte mail à interroger sont, eux, toujours configurés par
client dans l'application (page Réglages), pas ici.
"""
from __future__ import annotations

import logging
import os
import time

from core.bootstrap import ensure_defaults
from core.email_poller import executer_un_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("email_poller")


def main() -> None:
    interval = int(os.environ.get("LSPENNYLANE_POLL_INTERVAL_SECONDS", "300"))
    ensure_defaults()

    log.info("Service de fetch LightSpeed démarré (intervalle %ss).", interval)
    while True:
        try:
            executer_un_cycle()
        except Exception:  # pragma: no cover - le service ne doit jamais s'arrêter sur une erreur ponctuelle
            log.exception("Échec du cycle de fetch — nouvelle tentative au prochain intervalle.")
        time.sleep(interval)


if __name__ == "__main__":
    main()
