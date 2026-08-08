"""Annullamento in blocco quando un operatore non c'è.

Capita: uno si ammala la mattina e in agenda ha otto persone che non lo
sanno. Farlo a mano vuol dire aprire Google, cancellare otto eventi, cercare
otto indirizzi e scrivere otto email — e la volta che si salta qualcuno,
quello si presenta al salone.

La regola che tiene insieme il modulo: **ogni appuntamento va per conto suo**.
Un'email che non parte non deve impedire l'annullamento degli altri, e un
evento che Google non trova non deve lasciare in agenda i rimanenti. Quello
che non è riuscito finisce nel resoconto, per nome, così il salone sa chi
deve chiamare.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def annulla_giornata(appuntamenti: list[dict], backends) -> dict:
    """Annulla gli appuntamenti indicati e avvisa i clienti.

    Ogni voce: app_id, gcal_event_id, cal_id, data_ora, servizi,
    cliente_nome, cliente_email, parrucchiere.

    Restituisce il resoconto da mostrare a chi ha premuto il bottone:
    quanti annullati, chi è stato avvisato e chi va chiamato a mano.
    """
    resoconto = {
        "annullati": 0,
        "avvisati": [],
        "da_chiamare": [],
        "problemi": [],
    }

    for app in appuntamenti:
        nome = app.get("cliente_nome") or "Cliente"

        # Prima il calendario: se fallisce l'annullamento va avanti lo stesso,
        # perché lasciare l'appuntamento buono nel database sarebbe peggio che
        # lasciare un evento orfano su Google.
        if app.get("gcal_event_id") and app.get("cal_id"):
            try:
                await backends.delete_event(app["gcal_event_id"], app["cal_id"])
            except Exception as errore:  # noqa: BLE001
                logger.warning(
                    "Assenza: evento %s non rimosso da Google: %s",
                    app["gcal_event_id"],
                    errore,
                )
                resoconto["problemi"].append(
                    f"{nome}: l'evento resta sul calendario di Google"
                )

        try:
            await backends.update_appointment_status(app["app_id"], "Cancellato")
        except Exception as errore:  # noqa: BLE001
            # Questo sì che è grave: l'appuntamento risulta ancora valido.
            logger.error(
                "Assenza: appuntamento %s non annullato: %s", app["app_id"], errore
            )
            resoconto["problemi"].append(f"{nome}: NON annullato, riprova")
            continue

        resoconto["annullati"] += 1

        email = app.get("cliente_email")
        if not email:
            # Dal sito l'email c'è quasi sempre, da WhatsApp spesso no.
            resoconto["da_chiamare"].append(
                {"nome": nome, "telefono": app.get("cliente_telefono")}
            )
            continue

        try:
            await backends.send_absence_email(
                to=email,
                nome=nome,
                data_ora=app["data_ora"],
                parrucchiere=app.get("parrucchiere") or "il tuo operatore",
                servizi=app.get("servizi") or [],
            )
            resoconto["avvisati"].append(nome)
        except Exception as errore:  # noqa: BLE001
            logger.warning("Assenza: email a %s non partita: %s", email, errore)
            resoconto["da_chiamare"].append(
                {"nome": nome, "telefono": app.get("cliente_telefono")}
            )

    return resoconto
