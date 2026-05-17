from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date


class ClienteBase(BaseModel):
    nome: Optional[str] = None
    cognome: Optional[str] = None
    telefono_wa: str
    email: Optional[str] = None
    canale_origine: str = "whatsapp"


class ClienteResponse(ClienteBase):
    id: int
    prima_visita: Optional[date] = None
    ultima_visita: Optional[date] = None

    class Config:
        from_attributes = True


class AppuntamentoBase(BaseModel):
    data_ora: datetime
    durata_min: int = 30
    servizi: Optional[List[str]] = None
    richieste_spec: Optional[str] = None


class AppuntamentoResponse(AppuntamentoBase):
    id: int
    cliente_id: int
    parrucchiere_id: Optional[int] = None
    stato: str = "Confermato"
    gcal_event_id: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SlotDisponibile(BaseModel):
    slot: str  # "2026-05-10T09:00"
    parrucchiere_cal_id: str


class ActionRequest(BaseModel):
    action: str
    data: Optional[str] = None
    parrucchiere: Optional[str] = None
    parrucchiere_cal_id: Optional[str] = None
    slot: Optional[str] = None
    servizi: Optional[List[str]] = None
    durata_min: Optional[int] = 30
    app_id: Optional[int] = None
    gcal_event_id: Optional[str] = None
