from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date,
    LargeBinary, Numeric,
)
from sqlalchemy.orm import relationship
from datetime import datetime
from models.database import Base


class Cliente(Base):
    __tablename__ = "clienti"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100))
    cognome = Column(String(100))
    telefono_wa = Column(String(20), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True)
    canale_origine = Column(String(20), default="whatsapp")  # whatsapp | web
    note_private = Column(Text)  # allergie, preferenze, note parrucchiere
    parrucchiere_pref_id = Column(Integer, ForeignKey("parrucchieri.id"), nullable=True)
    prima_visita = Column(Date, default=datetime.now)
    ultima_visita = Column(Date, default=datetime.now)

    # Relazioni
    parrucchiere_pref = relationship("Parrucchiere", back_populates="clienti_pref")
    appuntamenti = relationship("Appuntamento", back_populates="cliente")


class Parrucchiere(Base):
    __tablename__ = "parrucchieri"

    id = Column(Integer, primary_key=True, autoincrement=True)
    nome = Column(String(100), nullable=False)
    gcal_calendar_id = Column(String(255), nullable=False)
    attivo = Column(Boolean, default=True)
    # Nel database e non su disco: su Render il disco è effimero e una foto
    # caricata dal pannello sparirebbe al primo deploy. Finché è vuota,
    # l'avatar lo disegna services/avatar.py con le iniziali.
    foto = Column(LargeBinary, nullable=True)
    foto_mime = Column(String(50), nullable=True)
    # False: lavora negli orari del salone, come è sempre stato. True: valgono
    # le fasce in `presenze`, e un giorno senza fasce vuol dire che non c'è.
    # Serve a distinguere "non ho ancora configurato niente" da "non lavora
    # mai": senza, i due casi sarebbero la stessa tabella vuota.
    orari_propri = Column(Boolean, default=False, nullable=False, server_default="0")

    presenze = relationship(
        "Presenza", back_populates="parrucchiere", cascade="all, delete-orphan"
    )

    # Relazioni
    clienti_pref = relationship("Cliente", back_populates="parrucchiere_pref")
    appuntamenti = relationship("Appuntamento", back_populates="parrucchiere")


class Presenza(Base):
    """Una fascia in cui un operatore è in salone, ripetuta ogni settimana.

    Righe separate invece di due colonne mattina/pomeriggio: chi fa orario
    continuato ne ha una, chi spezza ne ha due, e chi un giorno fa solo un
    paio d'ore non diventa un caso speciale.
    """

    __tablename__ = "presenze"

    id = Column(Integer, primary_key=True, autoincrement=True)
    parrucchiere_id = Column(
        Integer, ForeignKey("parrucchieri.id"), nullable=False, index=True
    )
    # 0 = lunedì ... 6 = domenica, come datetime.weekday()
    giorno = Column(Integer, nullable=False)
    ora_inizio = Column(String(5), nullable=False)  # "08:00"
    ora_fine = Column(String(5), nullable=False)  # "12:00"

    parrucchiere = relationship("Parrucchiere", back_populates="presenze")


class ServizioListino(Base):
    """Voce di listino: nome, prezzo e durata.

    Sta nel database (e non solo nel codice) perché il listino deve poter essere
    modificato dal pannello di gestione senza toccare il codice né rifare il
    deploy. Al primo avvio la tabella viene riempita dal catalogo iniziale.
    """

    __tablename__ = "servizi"

    id = Column(Integer, primary_key=True, autoincrement=True)
    codice = Column(String(50), unique=True, nullable=False, index=True)
    nome = Column(String(200), nullable=False)
    prezzo = Column(Numeric(6, 2), nullable=False)
    durata_min = Column(Integer, nullable=False, default=30)
    alias = Column(JSON)  # altri modi in cui i clienti chiamano il servizio
    ordine = Column(Integer, default=0)  # ordine di visualizzazione
    attivo = Column(Boolean, default=True)


class Appuntamento(Base):
    __tablename__ = "appuntamenti"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("clienti.id"), nullable=False)
    parrucchiere_id = Column(Integer, ForeignKey("parrucchieri.id"), nullable=True)
    data_ora = Column(DateTime, nullable=False, index=True)
    durata_min = Column(Integer, default=30)
    servizi = Column(JSON)  # ["Taglio", "Barba"]
    # Prezzo concordato al momento della prenotazione. Va salvato e non
    # ricalcolato: se domani il listino cambia, gli appuntamenti passati devono
    # continuare a riportare la cifra realmente pattuita col cliente.
    prezzo = Column(Numeric(6, 2))
    stato = Column(String(20), default="Confermato")  # Confermato/Cancellato/Completato/No-show
    richieste_spec = Column(Text)
    foto_riferimento = Column(Text)  # URL o path file salvato
    gcal_event_id = Column(String(255))
    note_post_app = Column(Text)  # note del parrucchiere dopo il servizio
    reminder_inviato = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    # Relazioni
    cliente = relationship("Cliente", back_populates="appuntamenti")
    parrucchiere = relationship("Parrucchiere", back_populates="appuntamenti")
