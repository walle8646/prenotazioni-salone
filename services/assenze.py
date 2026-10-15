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


def email_dello_spostamento(prima: str, dopo: str) -> str:
    """Quale delle due email va mandata quando un appuntamento si sposta.

    Non e' pignoleria. L'email dello spostamento barra la vecchia data e
    scrive la nuova: con giorno e ora identici si legge come un errore del
    salone. E quella del cambio operatore dice "stesso orario": mandarla
    quando l'ora e' cambiata lascia il cliente a presentarsi a quella vecchia.
    """
    return "spostamento" if dopo != prima else "cambio_operatore"


def togli_chi_non_viene(
    liberi: dict[str, set[str]], assente: str | None, giorno: str, giorno_assenza: str
) -> dict[str, set[str]]:
    """Le ore libere senza quelle di chi quel giorno non c'e'.

    Google lo dice libero, e ha ragione: l'assenza e' una decisione presa
    adesso, non un orario scritto in Presenze. Ma offrire di spostare un
    appuntamento proprio sulla persona che manca e' il modo piu' rapido di
    rifare domani lo stesso lavoro.

    **Solo nel giorno dell'assenza.** Il giorno dopo quell'operatore c'e', e
    toglierlo da tutto il calendario vorrebbe dire nascondere meta' dei posti
    liberi della settimana.
    """
    if not assente or giorno != giorno_assenza:
        return liberi
    return {nome: ore for nome, ore in liberi.items() if nome != assente}


def togli_il_giorno_che_manca(
    liberi: dict, assente: str | None, operatore: str | None, giorno_assenza: str
) -> dict:
    """Le ore libere di una settimana, senza il giorno in cui quello non c'e'.

    E' la stessa regola di `togli_chi_non_viene` vista dall'altra parte.
    Guardando la settimana di una persona sola le chiavi sono i giorni e non i
    nomi: se quella persona e' proprio chi non viene, il giorno dell'assenza
    deve restare senza verde — altrimenti la schermata che serve a salvare
    l'appuntamento propone di rimetterlo esattamente dov'era.

    Gli altri sei giorni restano: l'assenza e' di un giorno, e cancellargli
    tutta la settimana vorrebbe dire non poterglielo piu' dare nemmeno
    quando c'e'.
    """
    if not assente or operatore != assente:
        return liberi
    return {
        giorno: (set() if giorno.isoformat() == giorno_assenza else ore)
        for giorno, ore in liberi.items()
    }
