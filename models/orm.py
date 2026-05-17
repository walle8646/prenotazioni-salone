from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON, Date
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


class Appuntamento(Base):
    __tablename__ = "appuntamenti"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cliente_id = Column(Integer, ForeignKey("clienti.id"), nullable=False)
    parrucchiere_id = Column(Integer, ForeignKey("parrucchieri.id"), nullable=True)
    data_ora = Column(DateTime, nullable=False, index=True)
    durata_min = Column(Integer, default=30)
    servizi = Column(JSON)  # ["Taglio", "Barba"]
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
