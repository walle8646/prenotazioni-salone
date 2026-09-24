"""La giornata come la mostra un calendario: ore in verticale, una colonna per operatore.

Con settanta appuntamenti in un sabato, un elenco in ordine di ora non dice le
due cose che la receptionist cerca davvero: chi è libero adesso, e dove c'è un
buco per infilare chi telefona. Una griglia le dice senza leggere niente.

Qui c'è solo la disposizione — dove comincia ogni blocco, quanto è alto, chi
non è in salone a quell'ora. È logica pura, senza database né template, perché
un errore di mezz'ora in questi conti si vede solo guardando la pagina: meglio
poterlo provare con un appuntamento finto e un istante fissato.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from services.persone import telefono_da_mostrare

# Un appuntamento dura multipli di mezz'ora: la griglia ha righe da mezz'ora,
# e le altezze dei blocchi sono numeri di righe.
PASSO_MIN = 30

# Colore per servizio, non per operatore: gli operatori hanno già la loro
# colonna, mentre distinguere un colore da due ore da una barba da mezz'ora
# serve a capire la giornata prima di leggerla. Tinte chiare e un bordo
# pieno: il testo scuro sopra si legge sempre.
TINTE = (
    ("#e3f1ea", "#3f8f6b"),  # verde salvia
    ("#e4edf8", "#4a78b5"),  # azzurro
    ("#f6ecdc", "#b98535"),  # sabbia
    ("#efe7f5", "#8a62b0"),  # lavanda
    ("#fbe7e3", "#c0604c"),  # pesca
    ("#e6eef0", "#4f7f8a"),  # grigio petrolio
    ("#eeeede", "#8a8a3c"),  # oliva
)

SENZA_OPERATORE = "Senza operatore"


def _minuti(orario: str) -> int:
    ore, minuti = orario.split(":")
    return int(ore) * 60 + int(minuti)


def _ora(minuti: int) -> str:
    return f"{minuti // 60:02d}:{minuti % 60:02d}"


def tinta_del_servizio(nome: str | None, ordine: list[str]) -> tuple[str, str]:
    """Sempre la stessa tinta per lo stesso servizio.

    L'ordine del listino decide per quelli noti, così i primi servizi — i più
    richiesti — prendono i colori più distinguibili. Uno sconosciuto (sospeso,
    rinominato) si ricava dal nome con `hashlib` e non con `hash()`, che cambia
    a ogni avvio: altrimenti lo stesso servizio cambierebbe colore a ogni deploy.
    """
    if nome in ordine:
        return TINTE[ordine.index(nome) % len(TINTE)]
    impronta = hashlib.sha256((nome or "").encode("utf-8")).digest()
    return TINTE[impronta[0] % len(TINTE)]


def _corsie(blocchi: list[dict]) -> int:
    """Affianca gli appuntamenti che si sovrappongono nella stessa colonna.

    Non dovrebbe succedere — il bot non prenota due volte la stessa poltrona —
    ma un appuntamento inserito a mano o spostato male può farlo. Disegnati uno
    sopra l'altro, il secondo sparirebbe: proprio quello che va notato.
    """
    fine_corsia: list[int] = []
    for blocco in sorted(blocchi, key=lambda b: b["_inizio"]):
        for indice, fine in enumerate(fine_corsia):
            if fine <= blocco["_inizio"]:
                blocco["corsia"] = indice
                fine_corsia[indice] = blocco["_fine"]
                break
        else:
            blocco["corsia"] = len(fine_corsia)
            fine_corsia.append(blocco["_fine"])
    return max(1, len(fine_corsia))


def _zone_fuori_salone(nome: str, giorno: date, inizio: int, fine: int, e_in_salone) -> list[dict]:
    """Le mezz'ore in cui l'operatore non c'è, fuse in fasce continue."""
    zone: list[dict] = []
    for minuto in range(inizio, fine, PASSO_MIN):
        quando = f"{giorno.isoformat()}T{_ora(minuto)}"
        if e_in_salone(nome, quando):
            continue
        riga = (minuto - inizio) / PASSO_MIN
        if zone and zone[-1]["da"] + zone[-1]["per"] == riga:
            zone[-1]["per"] += 1
        else:
            zone.append({"da": riga, "per": 1})
    return zone


def _posti_liberi(
    nome: str,
    giorno: date,
    inizio: int,
    fine: int,
    liberi: dict[str, set[str]] | None,
    adesso: datetime | None,
) -> list[dict]:
    """Le mezz'ore in cui questo operatore può ricevere qualcuno.

    `liberi` è quello che dice Google. Se manca — non l'abbiamo chiesto, o non
    ha risposto — non si inventa niente: meglio nessun posto segnato che dei
    posti segnati liberi e in realtà occupati, perché su quelli qualcuno
    prenoterebbe davvero.

    Le ore già passate non si segnano: prenotare alle nove di stamattina non
    serve a nessuno, e riempirebbe di verde metà giornata.
    """
    if not liberi:
        return []

    suoi = liberi.get(nome) or set()
    if not suoi:
        return []

    trascorsi = None
    if adesso is not None and adesso.date() == giorno:
        trascorsi = adesso.hour * 60 + adesso.minute

    posti = []
    for minuto in range(inizio, fine, PASSO_MIN):
        if trascorsi is not None and minuto < trascorsi:
            continue
        quando = f"{giorno.isoformat()}T{_ora(minuto)}"
        if quando in suoi:
            posti.append(
                {
                    "da": (minuto - inizio) / PASSO_MIN,
                    "slot": quando,
                    "ora": _ora(minuto),
                }
            )
    return posti


def _blocco(app, inizio: int, fine: int, ordine_servizi: list[str], prezzo_di) -> dict:
    """Un appuntamento come lo disegna la griglia, in un posto solo.

    Lo usano sia la giornata sia la settimana: descritto due volte, prima o poi
    una delle due smette di nascondere il numero di sessione del sito o di
    dire il prezzo giusto.
    """
    cliente = app.cliente
    nome_cliente = " ".join(
        p
        for p in ((cliente.nome if cliente else None), (cliente.cognome if cliente else None))
        if p
    ) or "Cliente senza nome"
    telefono = (cliente.telefono_wa if cliente else "") or ""
    servizi = list(app.servizi or [])
    sfondo, bordo = tinta_del_servizio(servizi[0] if servizi else None, ordine_servizi)

    return {
        "id": app.id,
        "_inizio": inizio,
        "_fine": fine,
        "ora": _ora(inizio),
        "fine": _ora(fine),
        "cliente": nome_cliente,
        "cliente_id": cliente.id if cliente else None,
        # Chi arriva dal sito ha come "telefono" l'identificativo della
        # sessione, e chi non ne ha uno suo — un figlio — un segnaposto:
        # mostrarli farebbe credere a un numero da chiamare.
        "telefono": telefono_da_mostrare(telefono),
        "servizi": ", ".join(servizi) or "-",
        "prezzo": prezzo_di(app),
        "operatore": app.parrucchiere.nome if app.parrucchiere else SENZA_OPERATORE,
        "note": app.richieste_spec or "",
        "sfondo": sfondo,
        "bordo": bordo,
    }


def costruisci_agenda(
    appuntamenti: list,
    giorno: date,
    operatori: list[str],
    orari_del_giorno: list[tuple[str, str]],
    e_in_salone,
    prezzo_di,
    ordine_servizi: list[str],
    adesso: datetime | None = None,
    liberi: dict[str, set[str]] | None = None,
) -> dict:
    """Tutto quello che serve al template per disegnare la giornata.

    `e_in_salone` e `prezzo_di` arrivano da fuori per restare verificabili:
    in produzione sono quelle delle presenze e del listino, nei test due
    funzioni che rispondono come serve.

    L'intervallo mostrato va dall'apertura alla chiusura, **allargato** se un
    appuntamento cade fuori: uno preso prima che cambiassero gli orari, o
    inserito a mano, non deve sparire dalla vista proprio perché è anomalo.
    """
    inizi = [_minuti(a) for a, _ in orari_del_giorno]
    fini = [_minuti(b) for _, b in orari_del_giorno]

    blocchi_per_nome: dict[str, list[dict]] = {}
    for app in appuntamenti:
        inizio = app.data_ora.hour * 60 + app.data_ora.minute
        durata = app.durata_min or PASSO_MIN
        fine = inizio + durata
        inizi.append(inizio)
        fini.append(fine)

        nome = app.parrucchiere.nome if app.parrucchiere else SENZA_OPERATORE
        blocchi_per_nome.setdefault(nome, []).append(
            _blocco(app, inizio, fine, ordine_servizi, prezzo_di)
        )

    if not inizi:
        return {"chiuso": True, "colonne": [], "ore": [], "righe": 0, "adesso": None}

    # All'ora piena: una griglia che comincia alle 8:30 fa leggere male tutte
    # le etichette che vengono dopo.
    inizio_giorno = (min(inizi) // 60) * 60
    fine_giorno = -(-max(fini) // 60) * 60
    righe = (fine_giorno - inizio_giorno) // PASSO_MIN

    nomi = list(operatori)
    for nome in blocchi_per_nome:
        if nome not in nomi and nome != SENZA_OPERATORE:
            nomi.append(nome)  # a riposo, ma con appuntamenti ancora in agenda
    if SENZA_OPERATORE in blocchi_per_nome:
        nomi.append(SENZA_OPERATORE)

    colonne = []
    for nome in nomi:
        blocchi = blocchi_per_nome.get(nome, [])
        in_organico = nome in operatori
        zone = (
            _zone_fuori_salone(nome, giorno, inizio_giorno, fine_giorno, e_in_salone)
            if in_organico
            else []
        )
        # Chi quel giorno non c'è per niente e non ha appuntamenti è solo una
        # colonna grigia che ruba spazio a chi lavora.
        if in_organico and not blocchi and sum(z["per"] for z in zone) >= righe:
            continue

        # Gli spazi liberi contano più degli impegni: chi prenota a mano cerca
        # dove c'è posto, non chi è occupato. Arrivano da Google e non dal
        # database, perché un impegno segnato a mano sul calendario — una
        # pausa, una visita — occupa la poltrona esattamente come un
        # appuntamento, e il database non lo conosce.
        posti = _posti_liberi(nome, giorno, inizio_giorno, fine_giorno, liberi, adesso)

        corsie = _corsie(blocchi)
        for blocco in blocchi:
            blocco["da"] = (blocco["_inizio"] - inizio_giorno) / PASSO_MIN
            blocco["per"] = (blocco["_fine"] - blocco["_inizio"]) / PASSO_MIN
            blocco["corsie"] = corsie
        colonne.append(
            {
                "nome": nome,
                "foto": in_organico,
                "quanti": len(blocchi),
                "blocchi": sorted(blocchi, key=lambda b: b["_inizio"]),
                "fuori": zone,
                "liberi": posti,
            }
        )

    ore = [
        {"riga": (minuto - inizio_giorno) / PASSO_MIN, "testo": _ora(minuto)}
        for minuto in range(inizio_giorno, fine_giorno + 1, 60)
    ]

    linea_adesso = None
    if adesso is not None and adesso.date() == giorno:
        minuto = adesso.hour * 60 + adesso.minute
        if inizio_giorno <= minuto <= fine_giorno:
            linea_adesso = (minuto - inizio_giorno) / PASSO_MIN

    return {
        "chiuso": False,
        "colonne": colonne,
        "ore": ore,
        "righe": righe,
        "inizio": inizio_giorno,
        "adesso": linea_adesso,
    }


# I nomi dei giorni stanno nel codice perché nel container non c'è il locale
# italiano: senza, le colonne della settimana si intitolerebbero "Tue", "Wed".
GIORNI_CORTI = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]


def costruisci_settimana(
    appuntamenti: list,
    giorni: list[date],
    operatore: str,
    orari_per_giorno: dict,
    e_in_salone,
    prezzo_di,
    ordine_servizi: list[str],
    adesso: datetime | None = None,
    liberi: dict | None = None,
) -> dict:
    """La stessa griglia, ma con un giorno per colonna e un operatore solo.

    Serve a una domanda che la giornata non sa rispondere: "quando posso dare
    un appuntamento con Andrea?". Chiedendolo un giorno per volta si aprono
    sette schermate per scoprire che il primo posto è giovedì; qui si vede in
    una.

    Restituisce la stessa forma di `costruisci_agenda()` — colonne, ore,
    righe — così il template disegna la griglia una volta sola: due markup per
    la stessa cosa divergono, e uno dei due finisce per mostrare i blocchi
    mezz'ora fuori posto.
    """
    liberi = liberi or {}
    inizi: list[int] = []
    fini: list[int] = []
    for giorno in giorni:
        for apre, chiude in orari_per_giorno.get(giorno, []):
            inizi.append(_minuti(apre))
            fini.append(_minuti(chiude))

    blocchi_per_giorno: dict[date, list[dict]] = {}
    for app in appuntamenti:
        quando = app.data_ora
        inizio = quando.hour * 60 + quando.minute
        fine = inizio + (app.durata_min or PASSO_MIN)
        inizi.append(inizio)
        fini.append(fine)
        blocchi_per_giorno.setdefault(quando.date(), []).append(
            _blocco(app, inizio, fine, ordine_servizi, prezzo_di)
        )

    if not inizi:
        return {"chiuso": True, "colonne": [], "ore": [], "righe": 0, "adesso": None}

    inizio_giorno = (min(inizi) // 60) * 60
    fine_giorno = -(-max(fini) // 60) * 60
    righe = (fine_giorno - inizio_giorno) // PASSO_MIN

    colonne = []
    for giorno in giorni:
        aperto = bool(orari_per_giorno.get(giorno))
        blocchi = blocchi_per_giorno.get(giorno, [])
        # Un giorno di chiusura è tutto a righe, anche se l'operatore avrebbe
        # le sue fasce: il salone chiuso viene prima di chi ci lavora.
        zone = (
            _zone_fuori_salone(operatore, giorno, inizio_giorno, fine_giorno, e_in_salone)
            if aperto
            else [{"da": 0, "per": righe}]
        )
        posti = _posti_liberi(
            operatore,
            giorno,
            inizio_giorno,
            fine_giorno,
            {operatore: liberi.get(giorno, set())},
            adesso,
        )
        corsie = _corsie(blocchi)
        for blocco in blocchi:
            blocco["da"] = (blocco["_inizio"] - inizio_giorno) / PASSO_MIN
            blocco["per"] = (blocco["_fine"] - blocco["_inizio"]) / PASSO_MIN
            blocco["corsie"] = corsie
        colonne.append(
            {
                "nome": f"{GIORNI_CORTI[giorno.weekday()]} {giorno.day}",
                "foto": False,
                "iso": giorno.isoformat(),
                "aperto": aperto,
                "oggi": adesso is not None and adesso.date() == giorno,
                "quanti": len(blocchi),
                "blocchi": sorted(blocchi, key=lambda b: b["_inizio"]),
                "fuori": zone,
                "liberi": posti,
            }
        )

    ore = [
        {"riga": (minuto - inizio_giorno) / PASSO_MIN, "testo": _ora(minuto)}
        for minuto in range(inizio_giorno, fine_giorno + 1, 60)
    ]

    # Niente linea dell'ora corrente: qui attraverserebbe sette giorni, e in sei
    # di quelli non vuol dire niente. Oggi si riconosce dalla sua colonna.
    return {
        "chiuso": False,
        "colonne": colonne,
        "ore": ore,
        "righe": righe,
        "inizio": inizio_giorno,
        "adesso": None,
    }


MESI = [
    "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]


def costruisci_mesi(
    dal: date,
    carico: dict,
    aperto_il,
    oggi: date | None = None,
    scelto: date | None = None,
    quanti: int = 2,
) -> list[dict]:
    """Due mesi come un calendario da muro, con quanto è pieno ogni giorno.

    Sostituisce il campo "vai a un'altra data", che sapeva portare da qualche
    parte ma non dove conveniva andare: per trovare il primo giorno scarico si
    tiravano a indovinare date una per volta. Qui la distribuzione si vede
    prima di scegliere — due mesi bastano, perché nessuno prenota un taglio a
    tre mesi.

    Il riempimento è **relativo al giorno più carico dei due mesi**, non a una
    capienza teorica: il numero di poltrone cambia con le presenze, e una
    percentuale calcolata su una capienza sbagliata direbbe "pieno" dove c'è
    posto. Relativo risponde alla domanda vera, che è "dove c'è meno gente".
    """
    import calendar

    massimo = max(carico.values(), default=0)
    mesi = []
    primo = dal.replace(day=1)

    for _ in range(quanti):
        giorni_del_mese = calendar.monthrange(primo.year, primo.month)[1]
        # Le caselle vuote prima del primo: il mese comincia di lunedì nella
        # colonna del lunedì, altrimenti le settimane non si leggono in riga.
        celle: list = [None] * primo.weekday()
        for numero in range(1, giorni_del_mese + 1):
            giorno = date(primo.year, primo.month, numero)
            quanti_appuntamenti = carico.get(giorno, 0)
            celle.append(
                {
                    "iso": giorno.isoformat(),
                    "numero": numero,
                    "quanti": quanti_appuntamenti,
                    "riempimento": round(quanti_appuntamenti / massimo, 2) if massimo else 0,
                    "aperto": aperto_il(giorno),
                    "oggi": giorno == oggi,
                    "scelto": giorno == scelto,
                    "passato": oggi is not None and giorno < oggi,
                }
            )
        while len(celle) % 7:
            celle.append(None)

        mesi.append(
            {
                "nome": f"{MESI[primo.month - 1]} {primo.year}",
                "settimane": [celle[i : i + 7] for i in range(0, len(celle), 7)],
            }
        )
        primo = date(primo.year + primo.month // 12, primo.month % 12 + 1, 1)

    return mesi


def legenda(ordine_servizi: list[str], usati: set[str]) -> list[dict]:
    """I colori dei servizi presenti nella giornata, nell'ordine del listino."""
    return [
        {"nome": nome, "sfondo": s, "bordo": b}
        for nome in ordine_servizi
        if nome in usati
        for s, b in [tinta_del_servizio(nome, ordine_servizi)]
    ]
