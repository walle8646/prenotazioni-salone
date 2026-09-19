"""Test sulla giornata disegnata come calendario.

Un errore in questi conti non fa fallire niente: sposta un blocco di mezz'ora.
E un appuntamento disegnato alle 10 quando è alle 10:30 è peggio di un
elenco, perché la receptionist si fida di quello che vede e dà il posto a un
altro. Per questo la geometria si prova qui, con appuntamenti finti.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace as N

from services.agenda import (
    SENZA_OPERATORE,
    costruisci_agenda,
    costruisci_settimana,
    legenda,
    tinta_del_servizio,
)

GIORNO = date(2026, 9, 17)
OPERATORI = ["Simone Big", "Francesco", "Andrea"]
ORARI = [("09:00", "19:00")]
ORDINE = ["Taglio", "Taglio + Barba", "Barba", "Colore + Taglio + Trattamento capello"]


def _app(ora, operatore="Francesco", durata=30, servizi=("Taglio",), cliente="Mario Rossi", id_=1):
    ore, minuti = map(int, ora.split(":"))
    nome, cognome = cliente.split(" ", 1)
    return N(
        id=id_,
        data_ora=datetime(2026, 9, 17, ore, minuti),
        durata_min=durata,
        servizi=list(servizi),
        cliente=N(id=10 + id_, nome=nome, cognome=cognome, telefono_wa="393331234567"),
        parrucchiere=N(nome=operatore) if operatore else None,
        richieste_spec=None,
    )


def _sempre_in_salone(nome, quando):
    return True


def _agenda(appuntamenti, e_in_salone=_sempre_in_salone, orari=ORARI, adesso=None,
            liberi_google=None):
    return costruisci_agenda(
        appuntamenti,
        giorno=GIORNO,
        operatori=OPERATORI,
        orari_del_giorno=orari,
        e_in_salone=e_in_salone,
        prezzo_di=lambda a: "13,50 €",
        ordine_servizi=ORDINE,
        adesso=adesso,
        liberi=liberi_google,
    )


def _colonna(agenda, nome):
    return next(c for c in agenda["colonne"] if c["nome"] == nome)


# ------------------------------------------------------------- dove sta un blocco


def test_un_appuntamento_sta_alla_sua_mezz_ora():
    agenda = _agenda([_app("10:30")])
    blocco = _colonna(agenda, "Francesco")["blocchi"][0]

    assert agenda["inizio"] == 9 * 60
    assert blocco["da"] == 3, "10:30 è la terza mezz'ora dopo le 9"
    assert blocco["per"] == 1


def test_la_durata_decide_l_altezza():
    """Un colore da due ore occupa quattro righe, non una."""
    blocco = _colonna(_agenda([_app("11:00", durata=120)]), "Francesco")["blocchi"][0]
    assert blocco["per"] == 4
    assert blocco["fine"] == "13:00"


def test_la_giornata_va_dall_apertura_alla_chiusura():
    agenda = _agenda([])
    assert agenda["righe"] == 20
    assert [o["testo"] for o in agenda["ore"]][:2] == ["09:00", "10:00"]
    assert agenda["ore"][-1]["testo"] == "19:00"


def test_un_appuntamento_fuori_orario_allarga_la_giornata():
    """Anomalo è proprio il motivo per cui non deve sparire dalla vista."""
    agenda = _agenda([_app("08:30"), _app("19:00", id_=2)])

    assert agenda["inizio"] == 8 * 60, "si parte all'ora piena prima"
    assert agenda["ore"][-1]["testo"] == "20:00"


def test_a_salone_chiuso_senza_appuntamenti_non_c_e_griglia():
    assert _agenda([], orari=[])["chiuso"] is True


def test_a_salone_chiuso_con_appuntamenti_la_griglia_c_e():
    agenda = _agenda([_app("10:00")], orari=[])
    assert agenda["chiuso"] is False
    assert _colonna(agenda, "Francesco")["quanti"] == 1


# ----------------------------------------------------------------- le colonne


def test_una_colonna_per_operatore_nell_ordine_del_salone():
    agenda = _agenda([_app("10:00", "Andrea")])
    assert [c["nome"] for c in agenda["colonne"]] == OPERATORI


def test_chi_non_c_e_per_niente_e_non_ha_appuntamenti_sparisce():
    """Una colonna tutta grigia ruba spazio a chi lavora."""
    def solo_francesco(nome, quando):
        return nome == "Francesco"

    agenda = _agenda([], e_in_salone=solo_francesco)
    assert [c["nome"] for c in agenda["colonne"]] == ["Francesco"]


def test_chi_non_c_e_ma_ha_appuntamenti_resta():
    def nessuno(nome, quando):
        return False

    agenda = _agenda([_app("10:00", "Andrea")], e_in_salone=nessuno)
    assert "Andrea" in [c["nome"] for c in agenda["colonne"]]


def test_le_ore_fuori_salone_sono_fasce_continue():
    """Mattina sì, pomeriggio no: una fascia sola dalle 13, non dodici righe."""
    def solo_mattina(nome, quando):
        return quando[11:] < "13:00"

    zone = _colonna(_agenda([_app("10:00")], e_in_salone=solo_mattina), "Francesco")["fuori"]
    assert zone == [{"da": 8, "per": 12}]


def test_un_operatore_a_riposo_con_appuntamenti_ha_la_sua_colonna():
    agenda = _agenda([_app("10:00", "Giava")])
    assert agenda["colonne"][-1]["nome"] == "Giava"


def test_senza_operatore_va_in_fondo():
    agenda = _agenda([_app("10:00", operatore=None)])
    assert agenda["colonne"][-1]["nome"] == SENZA_OPERATORE


# ----------------------------------------------------------- sovrapposizioni


def test_due_appuntamenti_sovrapposti_si_affiancano():
    """Disegnati uno sopra l'altro, il secondo sparirebbe: è quello da notare."""
    blocchi = _colonna(
        _agenda([_app("10:00", durata=60), _app("10:30", id_=2)]), "Francesco"
    )["blocchi"]

    assert {b["corsia"] for b in blocchi} == {0, 1}
    assert all(b["corsie"] == 2 for b in blocchi)


def test_appuntamenti_uno_dopo_l_altro_restano_a_tutta_larghezza():
    blocchi = _colonna(_agenda([_app("10:00"), _app("10:30", id_=2)]), "Francesco")["blocchi"]
    assert all(b["corsie"] == 1 for b in blocchi)


# ------------------------------------------------------------------ dettagli


def test_la_linea_di_adesso_solo_oggi():
    oggi = _agenda([], adesso=datetime(2026, 9, 17, 11, 15))
    domani = _agenda([], adesso=datetime(2026, 9, 18, 11, 15))

    assert oggi["adesso"] == 4.5
    assert domani["adesso"] is None


def test_il_numero_di_sessione_del_sito_non_sembra_un_telefono():
    app = _app("10:00")
    app.cliente.telefono_wa = "web_4f1c9a"
    blocco = _colonna(_agenda([app]), "Francesco")["blocchi"][0]
    assert blocco["telefono"] == ""


def test_lo_stesso_servizio_ha_sempre_la_stessa_tinta():
    assert tinta_del_servizio("Barba", ORDINE) == tinta_del_servizio("Barba", ORDINE)
    assert tinta_del_servizio("Taglio", ORDINE) != tinta_del_servizio("Barba", ORDINE)
    # uno sconosciuto non esplode e non cambia fra una chiamata e l'altra
    assert tinta_del_servizio("Servizio sospeso", ORDINE) == tinta_del_servizio("Servizio sospeso", ORDINE)


def test_la_legenda_mostra_solo_i_servizi_della_giornata():
    assert [v["nome"] for v in legenda(ORDINE, {"Barba", "Taglio"})] == ["Taglio", "Barba"]


# ----------------------------------------------------- dove c'è posto libero
#
# Il verde è quello che si cerca guardando questa schermata: non chi è
# occupato, ma dove mettere il cliente che si ha al telefono. Sbagliarlo
# significa far prenotare su una poltrona già presa.


def test_i_posti_liberi_sono_quelli_che_dice_google():
    liberi = {"Francesco": {"2026-09-17T10:00", "2026-09-17T10:30"}}
    colonna = _colonna(_agenda([], liberi_google=liberi), "Francesco")

    assert [p["ora"] for p in colonna["liberi"]] == ["10:00", "10:30"]
    assert colonna["liberi"][0]["da"] == 2, "le 10 sono la seconda mezz'ora dopo le 9"


def test_senza_risposta_da_google_non_si_inventa_niente():
    """Meglio nessun posto segnato che posti segnati liberi e in realtà presi:
    su quelli qualcuno prenoterebbe davvero."""
    colonna = _colonna(_agenda([], liberi_google=None), "Francesco")
    assert colonna["liberi"] == []


def test_le_ore_gia_passate_non_si_offrono():
    liberi = {"Francesco": {"2026-09-17T09:00", "2026-09-17T15:00"}}
    agenda = _agenda([], liberi_google=liberi, adesso=datetime(2026, 9, 17, 11, 0))

    assert [p["ora"] for p in _colonna(agenda, "Francesco")["liberi"]] == ["15:00"]


def test_in_un_altro_giorno_valgono_tutte_le_ore():
    """L'ora corrente taglia solo la giornata di oggi."""
    liberi = {"Francesco": {"2026-09-17T09:00", "2026-09-17T15:00"}}
    agenda = _agenda([], liberi_google=liberi, adesso=datetime(2026, 9, 16, 11, 0))

    assert len(_colonna(agenda, "Francesco")["liberi"]) == 2


# ------------------------------------------- la settimana di un operatore
#
# Stessa griglia, altro significato delle colonne: non sei persone in un
# giorno, ma un giorno per colonna e una persona sola. Serve a rispondere a
# "quando me lo dai con Andrea?" senza aprire sette schermate. Qui si sbaglia
# nello stesso modo dell'altra vista — un blocco mezz'ora fuori posto — con in
# più un errore nuovo e peggiore: metterlo nel giorno sbagliato.

SETTE = [GIORNO + timedelta(days=i) for i in range(7)]
APERTI = {g: ([] if g.weekday() in (6, 0) else [ORARI[0]]) for g in SETTE}


def _app_del(giorno, ora="10:00", durata=30, id_=1, cliente="Mario Rossi"):
    ore, minuti = map(int, ora.split(":"))
    nome, cognome = cliente.split(" ", 1)
    return N(
        id=id_,
        data_ora=datetime.combine(giorno, datetime.min.time()).replace(hour=ore, minute=minuti),
        durata_min=durata,
        servizi=["Taglio"],
        cliente=N(id=10 + id_, nome=nome, cognome=cognome, telefono_wa="393331234567"),
        parrucchiere=N(nome="Francesco"),
        richieste_spec=None,
    )


def _settimana(appuntamenti=(), liberi=None, adesso=None, orari=None, e_in_salone=_sempre_in_salone):
    return costruisci_settimana(
        list(appuntamenti),
        giorni=SETTE,
        operatore="Francesco",
        orari_per_giorno=orari if orari is not None else APERTI,
        e_in_salone=e_in_salone,
        prezzo_di=lambda a: "13,50 €",
        ordine_servizi=ORDINE,
        adesso=adesso,
        liberi=liberi,
    )


def test_una_colonna_per_giorno_nell_ordine_della_settimana():
    agenda = _settimana()
    assert len(agenda["colonne"]) == 7
    assert agenda["colonne"][0]["nome"] == "Gio 17"
    assert [c["iso"] for c in agenda["colonne"]][-1] == SETTE[-1].isoformat()


def test_un_appuntamento_sta_nel_suo_giorno_e_alla_sua_ora():
    """L'errore nuovo di questa vista: il blocco nel giorno sbagliato."""
    agenda = _settimana([_app_del(SETTE[2], "10:30")])

    quanti = [c["quanti"] for c in agenda["colonne"]]
    assert quanti == [0, 0, 1, 0, 0, 0, 0]
    blocco = agenda["colonne"][2]["blocchi"][0]
    assert blocco["da"] == 3, "10:30 è la terza mezz'ora dopo le 9"


def test_i_posti_liberi_sono_quelli_del_giorno_giusto():
    liberi = {SETTE[1]: {f"{SETTE[1]}T11:00"}, SETTE[3]: {f"{SETTE[3]}T09:00"}}
    colonne = _settimana(liberi=liberi)["colonne"]

    assert [len(c["liberi"]) for c in colonne] == [0, 1, 0, 1, 0, 0, 0]
    assert colonne[1]["liberi"][0]["ora"] == "11:00"


def test_un_giorno_di_chiusura_e_tutto_a_righe():
    """Il salone chiuso viene prima delle fasce di chi ci lavora: senza, la
    domenica sembrerebbe una giornata normale e vuota."""
    domenica = next(c for c, g in zip(_settimana()["colonne"], SETTE) if g.weekday() == 6)

    assert domenica["aperto"] is False
    assert domenica["fuori"] == [{"da": 0, "per": 20}]


def test_le_ore_vanno_dall_apertura_alla_chiusura_della_settimana():
    agenda = _settimana()
    assert agenda["righe"] == 20
    assert agenda["ore"][0]["testo"] == "09:00"
    assert agenda["ore"][-1]["testo"] == "19:00"


def test_un_appuntamento_fuori_orario_allarga_tutta_la_settimana():
    agenda = _settimana([_app_del(SETTE[2], "08:30")])
    assert agenda["inizio"] == 8 * 60


def test_senza_niente_da_mostrare_non_c_e_griglia():
    assert _settimana(orari={g: [] for g in SETTE})["chiuso"] is True


def test_oggi_si_riconosce_dalla_sua_colonna():
    """La linea dell'ora corrente qui attraverserebbe sette giorni, e in sei
    non vorrebbe dire niente: al suo posto si marca la colonna."""
    agenda = _settimana(adesso=datetime.combine(SETTE[2], datetime.min.time()).replace(hour=11))

    assert agenda["adesso"] is None
    assert [c["oggi"] for c in agenda["colonne"]] == [False, False, True, False, False, False, False]


def test_le_ore_gia_passate_di_oggi_non_si_offrono():
    liberi = {SETTE[2]: {f"{SETTE[2]}T09:00", f"{SETTE[2]}T15:00"}}
    agenda = _settimana(
        liberi=liberi,
        adesso=datetime.combine(SETTE[2], datetime.min.time()).replace(hour=11),
    )

    assert [p["ora"] for p in agenda["colonne"][2]["liberi"]] == ["15:00"]
