from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date,
    Numeric,
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

    # Relazioni
    clienti_pref = relationship("Cliente", back_populates="parrucchiere_pref")
    appuntamenti = relationship("Appuntamento", back_populates="parrucchiere")


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
