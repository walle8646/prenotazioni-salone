"""Richiama l'attenzione su chi aspetta una persona e nessuno ha preso in mano.

La notifica parte quando il cliente chiede di parlare con qualcuno, e poi a
ogni suo messaggio successivo. Ma chi aspetta smette di scrivere — e' quello
che fa chi aspetta — e in quel caso parte una notifica sola. Se in quel momento
chi e' in salone ha le mani nei capelli di qualcuno, il cliente resta li' per
24 ore, finche' il bot non riprende in mano la conversazione.

Da qui in poi, una seconda occasione.

Due cose che non sono semplificabili.

**Si sollecita una volta sola**, e il modo per ottenerlo senza una colonna in
piu' e' la stessa fascia temporale del promemoria a 12 ore: si guardano le
conversazioni aperte fra `MINUTI_PRIMA` e `MINUTI_PRIMA + INTERVALLO_MINUTI`
fa. Larga quanto l'intervallo fra due giri, ogni conversazione ci cade dentro
esattamente una volta. Un giro saltato — un riavvio — fa perdere il sollecito
a chi stava in quella fascia: e' un sollecito, non una prenotazione.

**Solo a salone aperto.** Fuori orario non c'e' nessuno da richiamare, e una
notifica alle undici di sera insegna solo a silenziare le notifiche.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Quanto si lascia a chi e' in salone prima di richiamarlo. Dieci minuti e'
# quanto aspetta un cliente prima di pensare che non gli risponde nessuno.
MINUTI_PRIMA = 10

# Ogni quanto gira. Decide anche la larghezza della fascia, quindi cambiarlo
# qui basta: non c'e' un secondo posto che possa restare indietro.
INTERVALLO_MINUTI = 5


def _salone_aperto(adesso) -> bool:
    """Se a quest'ora c'e' qualcuno da richiamare.

    Si guardano gli orari veri, quelli che si cambiano da Presenze, non una
    costante: un salone che da ieri chiude il mercoledi' non deve mandare
    solleciti il mercoledi'.
    """
    from services.slots import chiusure, orari_salone

    if adesso.date().isoformat() in chiusure():
        return False
    fasce = (orari_salone() or {}).get(adesso.weekday()) or []
    ora = adesso.strftime("%H:%M")
    return any(inizio <= ora <= fine for inizio, fine in fasce)


async def sollecita_conversazioni_in_attesa() -> int:
    """Manda una seconda notifica per chi aspetta da un po'. Quanti ne ha trovati.

    Due orologi diversi, e non e' una svista. **Se il salone e' aperto** lo
    dice l'ora di Roma, perche' gli orari sono quelli della saracinesca.
    **Da quanto aspetta un cliente** si misura invece con lo stesso orologio
    che ha scritto la colonna, cioe' `datetime.now()` senza fuso: su Render il
    container sta a UTC, e confrontare un'ora con fuso contro una colonna
    senza fa fallire la query — `can't subtract offset-naive and offset-aware
    datetimes`. Visto in produzione, ogni cinque minuti.
    """
    from datetime import datetime, timedelta

    from services.db_service import conversazioni_in_attesa_da
    from services.slots import adesso_salone

    if not _salone_aperto(adesso_salone()):
        return 0

    adesso = datetime.now()
    da = adesso - timedelta(minutes=MINUTI_PRIMA + INTERVALLO_MINUTI)
    a = adesso - timedelta(minutes=MINUTI_PRIMA)

    try:
        conversazioni = await conversazioni_in_attesa_da(da, a)
    except Exception:  # noqa: BLE001
        logger.exception("Non riesco a sapere chi sta aspettando")
        return 0

    for conversazione in conversazioni:
        chi = conversazione.get("nome") or conversazione.get("telefono")
        try:
            from services.push import avvisa

            await avvisa(
                titolo=f"{chi} aspetta ancora",
                testo=(
                    "Ha chiesto di parlare con una persona "
                    f"{MINUTI_PRIMA} minuti fa e non ha ancora risposta."
                ),
                url=f"/admin/conversazioni/{conversazione['id']}",
            )
        except Exception:  # noqa: BLE001
            logger.warning("Sollecito non inviato per %s", chi, exc_info=True)

    if conversazioni:
        logger.info("Sollecitate %s conversazioni senza risposta", len(conversazioni))
    return len(conversazioni)
