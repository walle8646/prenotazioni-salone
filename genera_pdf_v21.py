#!/usr/bin/env python3
"""Genera GUIDA__1.PDF v2.1 — PostgreSQL + Pannello Admin"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether
)
from reportlab.lib import colors
import os

# Colors
RED_HEADER = HexColor("#C0392B")
DARK_RED = HexColor("#922B21")
LIGHT_GRAY = HexColor("#F5F5F5")
TABLE_HEADER_BG = HexColor("#2C3E50")
TABLE_ALT_BG = HexColor("#F8F9FA")
BLUE_LINK = HexColor("#2980B9")

WIDTH, HEIGHT = A4

def build_styles():
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        'CoverTitle', parent=styles['Title'],
        fontSize=22, leading=28, textColor=black,
        spaceAfter=6, alignment=TA_CENTER, fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        'CoverSubtitle', parent=styles['Normal'],
        fontSize=12, leading=16, textColor=HexColor("#555555"),
        spaceAfter=4, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        'CoverItem', parent=styles['Normal'],
        fontSize=10, leading=14, textColor=HexColor("#333333"),
        spaceAfter=2, alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        'SectionTitle', parent=styles['Heading1'],
        fontSize=16, leading=20, textColor=black,
        spaceBefore=12, spaceAfter=8, fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        'SubSection', parent=styles['Heading2'],
        fontSize=13, leading=17, textColor=HexColor("#2C3E50"),
        spaceBefore=10, spaceAfter=6, fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        'SubSubSection', parent=styles['Heading3'],
        fontSize=11, leading=15, textColor=HexColor("#34495E"),
        spaceBefore=8, spaceAfter=4, fontName='Helvetica-Bold'
    ))
    styles.add(ParagraphStyle(
        'BodyText2', parent=styles['Normal'],
        fontSize=9.5, leading=13, textColor=HexColor("#333333"),
        spaceAfter=4, alignment=TA_JUSTIFY
    ))
    styles.add(ParagraphStyle(
        'BulletCustom', parent=styles['Normal'],
        fontSize=9.5, leading=13, textColor=HexColor("#333333"),
        leftIndent=20, bulletIndent=8, spaceAfter=3
    ))
    styles.add(ParagraphStyle(
        'CodeBlock', parent=styles['Normal'],
        fontSize=8, leading=11, fontName='Courier',
        textColor=HexColor("#2C3E50"), backColor=LIGHT_GRAY,
        leftIndent=10, rightIndent=10, spaceBefore=4, spaceAfter=4
    ))
    styles.add(ParagraphStyle(
        'Footer', parent=styles['Normal'],
        fontSize=8, leading=10, textColor=HexColor("#888888"),
        alignment=TA_CENTER
    ))
    styles.add(ParagraphStyle(
        'TableCell', parent=styles['Normal'],
        fontSize=8.5, leading=11, textColor=HexColor("#333333")
    ))
    styles.add(ParagraphStyle(
        'TableHeader', parent=styles['Normal'],
        fontSize=8.5, leading=11, textColor=white, fontName='Helvetica-Bold'
    ))
    return styles

def header_footer(canvas, doc):
    canvas.saveState()
    # Red header bar
    canvas.setFillColor(RED_HEADER)
    canvas.rect(0, HEIGHT - 18*mm, WIDTH, 18*mm, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(15*mm, HEIGHT - 12*mm, "Guida Tecnica — Salone Nadia — v2.1")
    # Footer
    canvas.setFillColor(HexColor("#888888"))
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(WIDTH/2, 10*mm, f"Pagina {doc.page}")
    canvas.restoreState()

def make_table(headers, rows, col_widths=None):
    """Create a formatted table."""
    s = getSampleStyleSheet()
    hdr_style = ParagraphStyle('th', fontSize=8.5, leading=11, textColor=white, fontName='Helvetica-Bold')
    cell_style = ParagraphStyle('td', fontSize=8.5, leading=11, textColor=HexColor("#333333"))

    data = [[Paragraph(h, hdr_style) for h in headers]]
    for row in rows:
        data.append([Paragraph(str(c), cell_style) for c in row])

    if col_widths is None:
        col_widths = [WIDTH * 0.85 / len(headers)] * len(headers)

    t = Table(data, colWidths=col_widths)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), TABLE_HEADER_BG),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8.5),
        ('ALIGN', (0, 0), (-1, 0), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor("#CCCCCC")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
    ]
    # Alternate row colors
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), TABLE_ALT_BG))

    t.setStyle(TableStyle(style_cmds))
    return t

def bullet(text, styles):
    return Paragraph(f"<bullet>&bull;</bullet> {text}", styles['BulletCustom'])

def build_pdf():
    styles = build_styles()
    output_path = "/sessions/amazing-intelligent-davinci/mnt/parrucchieri-prenotazione-bot/GUIDA__1.PDF"

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=25*mm,
        bottomMargin=20*mm,
        leftMargin=15*mm,
        rightMargin=15*mm
    )

    story = []
    usable = WIDTH - 30*mm

    # =========================================================================
    # PAGE 1: COVER
    # =========================================================================
    story.append(Spacer(1, 40*mm))
    story.append(Paragraph("GUIDA TECNICA DI SVILUPPO", styles['CoverTitle']))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Sistema AI WhatsApp per prenotazioni — Salone Nadia", styles['CoverSubtitle']))
    story.append(Spacer(1, 20))

    cover_items = [
        ("Canale cliente", "WhatsApp Business (Cloud API Meta)"),
        ("AI conversazionale", "Claude API (claude-sonnet-4-20250514)"),
        ("Calendario", "Google Calendar API"),
        ("Backend", "Python / FastAPI"),
        ("Hosting", "Render (free per test, Starter per produzione)"),
        ("Sessioni", "Redis (Render)"),
        ("CRM", "PostgreSQL (Render)"),
        ("Accesso CRM", "Pannello Admin web (receptionist)"),
        ("Versione documento", "2.1 — maggio 2026"),
    ]
    for label, value in cover_items:
        story.append(Paragraph(f"<b>{label}:</b> {value}", styles['CoverItem']))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: SEZIONE 1 — Panoramica
    # =========================================================================
    story.append(Paragraph("1. Panoramica del progetto", styles['SectionTitle']))
    story.append(Paragraph(
        "Il sistema sostituisce la gestione manuale degli appuntamenti via WhatsApp, oggi gestita dalla "
        "receptionist. Un assistente AI risponde ai clienti sul canale WhatsApp del salone, gestisce l'intero flusso di "
        "prenotazione in autonomia e salva tutte le informazioni raccolte in una scheda cliente consultabile dal "
        "pannello admin prima di ogni appuntamento.",
        styles['BodyText2']
    ))
    story.append(Paragraph("1.1 Obiettivi", styles['SubSection']))
    obiettivi = [
        "Raccogliere prenotazioni 24/7 senza intervento umano per i casi standard",
        "Raccogliere informazioni pre-appuntamento (intake) in modo strutturato",
        "Gestire la disponibilita in tempo reale consultando Google Calendar",
        "Assegnare il parrucchiere corretto secondo le regole del salone",
        "Mettere a disposizione della receptionist una scheda cliente completa prima di ogni appuntamento",
    ]
    for o in obiettivi:
        story.append(bullet(o, styles))

    story.append(Paragraph("1.2 Flusso principale", styles['SubSection']))
    story.append(Paragraph("Il flusso standard si articola in quattro fasi:", styles['BodyText2']))
    flusso = [
        "1. Il cliente scrive su WhatsApp — l'AI saluta e chiede cosa desidera",
        "2. L'AI verifica disponibilita su Google Calendar e propone slot liberi",
        "3. Confermato lo slot, l'AI raccoglie le informazioni di intake (nome, cognome, telefono, richieste speciali, eventuale foto di riferimento)",
        "4. Il backend salva tutto in PostgreSQL, crea l'evento su Google Calendar e manda conferma al cliente",
    ]
    for f in flusso:
        story.append(bullet(f, styles))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 3-4: SEZIONE 2 — Architettura
    # =========================================================================
    story.append(Paragraph("2. Architettura del sistema", styles['SectionTitle']))
    story.append(Paragraph("2.1 Schema del flusso dati", styles['SubSection']))

    schema_text = """Cliente WhatsApp
        |
        v
WhatsApp Cloud API (Meta) --- webhook ---> FastAPI (Render)
        |
        +----------------+----------------+----------------+
        v                v                v                v
   Claude API    Google Calendar    PostgreSQL    Pannello Admin
   (AI chat)     (disponibilita)      (DB)       (receptionist)
        |                |
        +----------------+
        |
   risposta WhatsApp
   via Cloud API -> cliente"""
    story.append(Paragraph(schema_text.replace('\n', '<br/>').replace('  ', '&nbsp;&nbsp;'), styles['CodeBlock']))

    story.append(Paragraph("2.2 Componenti e responsabilita", styles['SubSection']))
    comp_rows = [
        ["WhatsApp Cloud API (Meta)",
         "Riceve i messaggi WhatsApp in entrata e li inoltra al backend via webhook. Invia le risposte al cliente. Nessun intermediario BSP: connessione diretta con Meta."],
        ["FastAPI Backend (Render)",
         "Orchestratore centrale: riceve il webhook, gestisce lo stato conversazionale (Redis), chiama Claude API, interroga Google Calendar per verificare/creare slot, salva in PostgreSQL. Esegue i job schedulati (reminder, ricontatto). Deploy automatico da Git."],
        ["Redis (Render)",
         "Store per le sessioni conversazionali. Veloce, supporta TTL nativo per scadenza automatica delle sessioni inattive (2 ore). Piano free di Render sufficiente (25MB)."],
        ["Claude API",
         "Gestisce la logica conversazionale. Riceve il messaggio del cliente + la storia della conversazione + le istruzioni del salone e genera la risposta appropriata."],
        ["Google Calendar API",
         "Fonte di verita per la disponibilita. Vengono consultati i calendari di ogni parrucchiere e il calendario eccezioni del salone."],
        ["PostgreSQL (Render)",
         "Database relazionale per clienti, appuntamenti, parrucchieri. Transazioni ACID, nessun limite di record. Piano free 1GB su Render."],
        ["Pannello Admin",
         "Interfaccia web per la receptionist. Dashboard appuntamenti del giorno, scheda cliente. Autenticazione con cookie di sessione."],
    ]
    story.append(make_table(
        ["Componente", "Responsabilita"],
        comp_rows,
        [usable*0.25, usable*0.75]
    ))

    story.append(Paragraph("2.3 Perche questa architettura", styles['SubSection']))
    story.append(Paragraph(
        "Rispetto a un'architettura basata su n8n come orchestratore, la scelta di un backend Python monolitico su "
        "Render offre vantaggi significativi:", styles['BodyText2']
    ))
    arch_points = [
        "Gestione stato pulita: la logica conversazionale con sessioni e fasi si esprime naturalmente in codice Python",
        "Testabilita: ogni componente e testabile con pytest, ogni scenario simulabile",
        "Debug semplificato: log strutturati in un unico posto, stack trace leggibili",
        "Deploy zero-config: Render gestisce HTTPS, scaling, restart automatico. Deploy con git push",
        "Fase test gratuita: piano free di Render per sviluppo e test, poi Starter (~7$/mese) per produzione",
        "Versionamento: tutta la logica e codice in un repository Git",
        "Niente server da gestire: nessun Docker, nessun Caddy, nessun aggiornamento sistema operativo",
    ]
    for p in arch_points:
        story.append(bullet(p, styles))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 5-6: SEZIONE 3 — Google Calendar
    # =========================================================================
    story.append(Paragraph("3. Struttura Google Calendar", styles['SectionTitle']))
    story.append(Paragraph("3.1 Calendari da creare o mappare", styles['SubSection']))
    story.append(Paragraph(
        "Ogni parrucchiere deve avere un calendario Google dedicato. Oltre ai calendari individuali, serve un "
        "calendario centralizzato per le eccezioni del salone.", styles['BodyText2']
    ))
    cal_rows = [
        ["salone_eccezioni", "Chiusure, ferie, aperture straordinarie", "Nadia / receptionist"],
        ["parrucchiere_1", "Disponibilita e appuntamenti operatore 1", "Auto (sistema)"],
        ["parrucchiere_2", "Disponibilita e appuntamenti operatore 2", "Auto (sistema)"],
        ["parrucchiere_3 ... 6", "Idem per gli altri 4 operatori", "Auto (sistema)"],
    ]
    story.append(make_table(["Calendario", "Scopo", "Chi gestisce"], cal_rows, [usable*0.25, usable*0.45, usable*0.30]))

    story.append(Paragraph("3.2 Logica di controllo disponibilita", styles['SubSection']))
    story.append(Paragraph("Prima di proporre uno slot al cliente, il backend esegue questi controlli in ordine:", styles['BodyText2']))
    checks = [
        "Controlla il calendario salone_eccezioni: se lo slot ricade in un evento di chiusura, non e disponibile.",
        "Se il cliente ha un parrucchiere preferito, controlla solo il suo calendario.",
        "Se il cliente e indifferente, controlla tutti i calendari e restituisce il primo slot libero.",
        "Verifica che lo slot abbia almeno 30 minuti liberi (durata standard di ogni servizio).",
        "Per servizi multipli prenotati nello stesso appuntamento, verifica slot consecutivi liberi.",
    ]
    for c in checks:
        story.append(bullet(c, styles))

    story.append(Paragraph("3.3 Orari operativi", styles['SubSection']))
    orari_rows = [
        ["Martedi - Venerdi", "08:00-12:00 e 14:30-19:30", "Con pausa pranzo"],
        ["Sabato", "08:00-18:00", "Orario continuato, nessuna pausa"],
        ["Domenica - Lunedi", "Chiuso", "Tranne aperture straordinarie a dicembre"],
        ["Slot", "Ogni 30 minuti", "08:00, 08:30, 09:00 ..."],
    ]
    story.append(make_table(["Giorno", "Orario", "Note"], orari_rows, [usable*0.25, usable*0.35, usable*0.40]))

    story.append(Paragraph("3.4 Chiusure fisse annuali", styles['SubSection']))
    story.append(Paragraph("Da inserire come eventi ricorrenti nel calendario salone_eccezioni:", styles['BodyText2']))
    chiusure = [
        "25 e 26 dicembre, 1 gennaio, 6 gennaio, 15 agosto",
        "Ferie estive/invernali (da inserire anno per anno)",
        "Domeniche e lunedi di dicembre (aperture straordinarie da segnare come eccezioni positive)",
    ]
    for c in chiusure:
        story.append(bullet(c, styles))

    story.append(Paragraph("3.5 Gestione assenza improvvisa parrucchiere", styles['SubSection']))
    story.append(Paragraph(
        "Quando un parrucchiere si ammala, la receptionist crea manualmente un evento che blocca l'intera "
        "giornata nel calendario di quell'operatore. Il backend non proporra piu slot per quell'operatore. I clienti con "
        "appuntamento confermato vengono notificati via WhatsApp.", styles['BodyText2']
    ))
    story.append(Paragraph(
        "<b>Azione manuale richiesta:</b> la receptionist deve bloccare il calendario e attivare l'endpoint di notifica cancellazione.",
        styles['BodyText2']
    ))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 7-8: SEZIONE 4 — Struttura Database (PostgreSQL)
    # =========================================================================
    story.append(Paragraph("4. Struttura Database (PostgreSQL)", styles['SectionTitle']))

    story.append(Paragraph("4.1 Tabella: Clienti", styles['SubSection']))
    clienti_rows = [
        ["id", "SERIAL PK", "ID univoco cliente"],
        ["nome", "VARCHAR(100)", ""],
        ["cognome", "VARCHAR(100)", ""],
        ["telefono_wa", "VARCHAR(20) UNIQUE INDEX", "Numero WhatsApp (chiave di ricerca)"],
        ["note_private", "TEXT", "Allergie, preferenze, note parrucchiere"],
        ["parrucchiere_pref_id", "FK -> parrucchieri.id", "Operatore preferito (opzionale)"],
        ["prima_visita", "DATE", "Data primo appuntamento"],
        ["ultima_visita", "DATE", "Aggiornato ad ogni appuntamento"],
    ]
    story.append(make_table(["Campo", "Tipo", "Note"], clienti_rows, [usable*0.25, usable*0.30, usable*0.45]))

    story.append(Paragraph("4.2 Tabella: Appuntamenti", styles['SubSection']))
    app_rows = [
        ["id", "SERIAL PK", "ID univoco appuntamento"],
        ["cliente_id", "FK -> clienti.id", ""],
        ["parrucchiere_id", "FK -> parrucchieri.id", "Operatore assegnato"],
        ["data_ora", "TIMESTAMP INDEX", "Data e ora appuntamento"],
        ["durata_min", "INTEGER", "Calcolata in base ai servizi (multipli di 30)"],
        ["servizi", "JSON", "Taglio, Barba, Shampoo, ecc."],
        ["stato", "VARCHAR(20)", "Confermato / Cancellato / Completato / No-show"],
        ["richieste_spec", "TEXT", "Richieste speciali raccolte in intake"],
        ["foto_riferimento", "TEXT", "URL foto ispirazione inviate dal cliente"],
        ["gcal_event_id", "VARCHAR(255)", "ID evento Google Calendar"],
        ["note_post_app", "TEXT", "Note del parrucchiere dopo il servizio"],
        ["reminder_inviato", "BOOLEAN", "Per evitare reminder duplicati"],
        ["created_at", "TIMESTAMP", "Data creazione record"],
    ]
    story.append(make_table(["Campo", "Tipo", "Note"], app_rows, [usable*0.22, usable*0.28, usable*0.50]))

    story.append(Paragraph("4.3 Tabella: Parrucchieri", styles['SubSection']))
    parr_rows = [
        ["id", "SERIAL PK", "ID univoco parrucchiere"],
        ["nome", "VARCHAR(100)", ""],
        ["gcal_calendar_id", "VARCHAR(255)", "ID calendario Google Calendar"],
        ["attivo", "BOOLEAN", "Se disabilitato, non viene mai proposto"],
    ]
    story.append(make_table(["Campo", "Tipo", "Note"], parr_rows, [usable*0.25, usable*0.30, usable*0.45]))

    story.append(Paragraph("4.4 Pannello Admin per la receptionist", styles['SubSection']))
    story.append(Paragraph(
        "Il pannello admin e un'interfaccia web costruita con Jinja2 + HTMX, servita direttamente dal backend FastAPI. "
        "Fornisce alla receptionist un accesso semplice e immediato ai dati del salone.",
        styles['BodyText2']
    ))
    admin_rows = [
        ["/admin/dashboard",
         "Mostra appuntamenti del giorno con filtro data, stato Confermato, ordinamento cronologico."],
        ["/admin/cliente/{id}",
         "Scheda singolo cliente con storico appuntamenti, note private, parrucchiere preferito."],
        ["/admin/login",
         "Login con username/password (configurabili via env vars ADMIN_USERNAME e ADMIN_PASSWORD)."],
    ]
    story.append(make_table(["Pagina", "Descrizione"], admin_rows, [usable*0.30, usable*0.70]))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 9-10: SEZIONE 5 — WhatsApp Cloud API
    # =========================================================================
    story.append(Paragraph("5. WhatsApp Cloud API (Meta)", styles['SectionTitle']))
    story.append(Paragraph("5.1 Perche Cloud API invece di un BSP", styles['SubSection']))
    story.append(Paragraph(
        "La WhatsApp Cloud API di Meta elimina la necessita di un intermediario (BSP) come 360dialog:",
        styles['BodyText2']
    ))
    wa_points = [
        "Nessun canone mensile: l'accesso all'API e gratuito",
        "Messaggi di servizio gratuiti: tutte le risposte ai clienti che scrivono per primi sono gratuite e illimitate",
        "Si paga solo per messaggi proattivi: reminder, notifiche, ricontatto (utility/marketing)",
        "Connessione diretta con Meta: meno latenza, meno punti di failure",
    ]
    for p in wa_points:
        story.append(bullet(p, styles))

    story.append(Paragraph("5.2 Prerequisiti", styles['SubSection']))
    prereq = [
        "Account Meta Business Manager verificato",
        "App Meta for Developers con prodotto WhatsApp configurato",
        "Numero di telefono dedicato (migrazione dal numero esistente possibile)",
        "Token di accesso permanente (System User token)",
    ]
    for p in prereq:
        story.append(bullet(p, styles))

    story.append(Paragraph("5.3 Configurazione webhook", styles['SubSection']))
    story.append(Paragraph("Nel pannello Meta for Developers, configurare il webhook che punta al backend su Render:", styles['BodyText2']))
    webhook_text = """Webhook URL: https://salone-nadia-bot.onrender.com/webhook/whatsapp
Verify Token: [TOKEN_SEGRETO_CONDIVISO]
Campi sottoscritti: messages"""
    story.append(Paragraph(webhook_text.replace('\n', '<br/>'), styles['CodeBlock']))

    story.append(Paragraph("5.4 Template messaggi", styles['SubSection']))
    story.append(Paragraph(
        "WhatsApp richiede template approvati da Meta per i messaggi proattivi. Le risposte entro 24h sono gratuite e senza template.",
        styles['BodyText2']
    ))
    tmpl_rows = [
        ["conferma_prenotazione", "Ciao {{1}}, il tuo appuntamento e' confermato per il {{2}} alle {{3}} con {{4}}. A presto dal Salone Nadia!"],
        ["reminder_12h", "Ciao {{1}}, ti ricordiamo l'appuntamento di domani alle {{2}} con {{3}}. Per cancellare scrivi qui entro le prossime 12 ore."],
        ["cancellazione_operatore", "Ciao {{1}}, purtroppo {{2}} non e' disponibile il {{3}}. Scrivi qui per riprenota con un altro operatore o in un altro giorno."],
        ["ricontatto_inattivo", "Ciao {{1}}, e' da un po' che non ti vediamo al Salone Nadia. Vuoi prenotare un appuntamento?"],
    ]
    story.append(make_table(["Template", "Testo"], tmpl_rows, [usable*0.25, usable*0.75]))
    story.append(Paragraph("I template richiedono 24-48 ore per l'approvazione Meta. Sottomettere in anticipo.", styles['BodyText2']))

    story.append(Paragraph("5.5 Pricing stimato", styles['SubSection']))
    pricing_wa = [
        "Messaggi di servizio (risposte): gratuiti e illimitati",
        "Messaggi utility (reminder, conferme): ~0.03-0.05 EUR/msg in Italia",
        "Messaggi marketing (ricontatto): ~0.05-0.08 EUR/msg in Italia",
        "Stima mensile totale WhatsApp: 5-15 EUR/mese",
    ]
    for p in pricing_wa:
        story.append(bullet(p, styles))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 11-12: SEZIONE 6 — Backend FastAPI
    # =========================================================================
    story.append(Paragraph("6. Backend FastAPI", styles['SectionTitle']))
    story.append(Paragraph("6.1 Struttura del progetto", styles['SubSection']))

    proj_struct = """salone-nadia-bot/
|-- main.py                     # Entrypoint FastAPI + uvicorn
|-- config.py                   # Variabili di configurazione (env vars)
|-- routers/
|   |-- webhook.py              # Endpoint webhook WhatsApp
|   |-- admin.py                # Endpoint pannello admin + azioni receptionist
|-- services/
|   |-- conversation.py         # Logica conversazionale principale
|   |-- claude_client.py        # Wrapper Claude API
|   |-- calendar_service.py     # Google Calendar API
|   |-- db_service.py           # Operazioni CRUD PostgreSQL
|   |-- whatsapp_service.py     # Invio messaggi WhatsApp Cloud API
|   |-- session_manager.py      # Gestione sessioni Redis
|-- models/
|   |-- schemas.py              # Pydantic models
|   |-- database.py             # Connessione DB e engine SQLAlchemy
|   |-- orm.py                  # Modelli ORM SQLAlchemy
|-- templates/                  # Template Jinja2 per pannello admin
|-- static/                     # CSS/JS per pannello admin
|-- alembic/                    # Migrazioni database
|-- jobs/
|   |-- scheduler.py            # APScheduler per job periodici
|   |-- reminder_job.py         # Reminder 12h prima
|   |-- recontact_job.py        # Ricontatto clienti inattivi
|-- prompts/
|   |-- system_prompt.py        # Template system prompt Claude
|-- tests/
|-- render.yaml                 # Configurazione deploy Render
|-- requirements.txt
|-- .env.example"""
    story.append(Paragraph(proj_struct.replace('\n', '<br/>').replace('  ', '&nbsp;&nbsp;'), styles['CodeBlock']))

    story.append(Paragraph("6.2 Endpoint principali", styles['SubSection']))
    ep_rows = [
        ["GET", "/webhook/whatsapp", "Verifica webhook Meta (challenge handshake)"],
        ["POST", "/webhook/whatsapp", "Riceve messaggi WhatsApp in entrata"],
        ["POST", "/admin/cancel-notify", "Notifica cancellazione per assenza parrucchiere"],
        ["GET", "/admin/dashboard", "Dashboard appuntamenti (receptionist)"],
        ["GET", "/admin/cliente/{id}", "Scheda cliente con storico"],
        ["GET", "/admin/login", "Login pannello admin"],
        ["GET", "/health", "Health check per monitoraggio"],
    ]
    story.append(make_table(["Metodo", "Endpoint", "Descrizione"], ep_rows, [usable*0.12, usable*0.30, usable*0.58]))

    story.append(Paragraph("6.3 Flusso di un messaggio", styles['SubSection']))
    story.append(Paragraph("Quando un cliente invia un messaggio su WhatsApp:", styles['BodyText2']))
    msg_flow = [
        "1. Meta invia il webhook POST a /webhook/whatsapp",
        "2. Il router estrae numero, testo, tipo messaggio (testo/immagine/audio)",
        "3. session_manager carica la sessione da Redis (o ne crea una nuova)",
        "4. conversation.py determina la fase corrente e prepara il contesto",
        "5. Se serve verifica disponibilita, calendar_service interroga Google Calendar",
        "6. claude_client chiama Claude API con system prompt + history + contesto",
        "7. Se Claude restituisce un'azione JSON, il backend la esegue (Google Calendar, PostgreSQL)",
        "8. La risposta testuale viene inviata al cliente via whatsapp_service",
        "9. La sessione viene aggiornata in Redis con TTL di 2 ore",
    ]
    for m in msg_flow:
        story.append(bullet(m, styles))

    story.append(Paragraph("6.4 Gestione sessioni (Redis)", styles['SubSection']))
    story.append(Paragraph(
        "Redis gestisce le sessioni conversazionali. Su Render, il piano free offre 25MB — piu che sufficienti per le sessioni di un salone.",
        styles['BodyText2']
    ))
    redis_text = """Chiave Redis: session:{telefono_wa}
TTL: 7200 secondi (2 ore di inattivita)
Struttura JSON:
{
  "stato_flusso": "saluto|scelta_servizio|scelta_operatore|scelta_slot|intake|confermato",
  "history": [{"role": "user|assistant", "content": "..."}],
  "dati_temp": {"servizio": null, "parrucchiere": null, "slot": null, ...},
  "last_activity": "2026-05-14T10:30:00"
}"""
    story.append(Paragraph(redis_text.replace('\n', '<br/>').replace('  ', '&nbsp;&nbsp;'), styles['CodeBlock']))

    story.append(Paragraph("6.5 Job schedulati", styles['SubSection']))
    job_rows = [
        ["Reminder 12h", "Ogni 30 minuti", "Cerca appuntamenti confermati tra 11.5h e 12.5h da adesso. Invia reminder via template WhatsApp."],
        ["Ricontatto inattivi", "Ogni lunedi ore 10:00", "Cerca clienti con ultima_visita > 60 giorni fa. Genera messaggio via Claude. Invia via template marketing."],
    ]
    story.append(make_table(["Job", "Frequenza", "Logica"], job_rows, [usable*0.20, usable*0.20, usable*0.60]))
    story.append(Paragraph("Il job di ricontatto va attivato solo dopo che il sistema principale e stabile.", styles['BodyText2']))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 13: SEZIONE 7 — Claude API
    # =========================================================================
    story.append(Paragraph("7. Claude API — System prompt e logica AI", styles['SectionTitle']))

    story.append(Paragraph("7.1 Struttura del system prompt", styles['SubSection']))
    story.append(Paragraph(
        "Il system prompt viene costruito dinamicamente dal backend e passato a ogni chiamata Claude API. Contiene:",
        styles['BodyText2']
    ))
    sp_items = [
        "Identita e tono: chi e l'AI, come si chiama, come parla",
        "Contesto del salone: servizi, orari, parrucchieri, regole",
        "Stato corrente: fase in cui si trova il cliente",
        "Dati disponibilita: slot liberi gia calcolati dal backend",
        "Istruzioni azioni speciali: quando emettere CHECK_DISPONIBILITA, CREA_APPUNTAMENTO, ecc.",
    ]
    for s in sp_items:
        story.append(bullet(s, styles))

    story.append(Paragraph("7.2 Template system prompt (estratto)", styles['SubSection']))
    sp_template = """Sei Nadia, l'assistente virtuale del Salone Nadia.
Sei cordiale e professionale. Parli in italiano.

## INFORMAZIONI SUL SALONE
Orari: mar-ven 8:00-12:00 e 14:30-19:30, sab 8:00-18:00.
Chiuso domenica e lunedi (tranne dicembre).
Servizi: Taglio, Taglio+Shampoo, Taglio+Barba, Barba, Taglio+Barba+Shampoo
Durata: 30 min per servizio. Slot ogni 30 min.

## REGOLE
1. Non inventare mai disponibilita. Usa solo gli slot forniti.
2. Se il parrucchiere preferito non e' disponibile, offri alternative.
3. Per clienti nuovi, chiedi eta e tipo di taglio.
4. Non rispondere a domande non legate al salone.

## AZIONI SPECIALI
Quando servono dati, rispondi SOLO con il JSON:
{"action": "CHECK_DISPONIBILITA", "data": "2026-05-10", "parrucchiere": "Marco"}
{"action": "CREA_APPUNTAMENTO", "slot": "2026-05-10T09:00", ...}
{"action": "CANCELLA_APPUNTAMENTO", "app_id": "123"}"""
    story.append(Paragraph(sp_template.replace('\n', '<br/>').replace('  ', '&nbsp;&nbsp;'), styles['CodeBlock']))

    story.append(Paragraph("7.3 Gestione delle azioni", styles['SubSection']))
    story.append(Paragraph(
        "Quando Claude risponde con un JSON di azione, il backend intercetta la risposta, esegue l'azione "
        "(Google Calendar, PostgreSQL), poi richiama Claude con il risultato per ottenere il messaggio da inviare al cliente.",
        styles['BodyText2']
    ))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 14: SEZIONE 8 — Logiche business
    # =========================================================================
    story.append(Paragraph("8. Logiche di business specifiche", styles['SectionTitle']))

    story.append(Paragraph("8.1 Regole di assegnazione parrucchiere", styles['SubSection']))
    assign_rows = [
        ["Cliente con preferenza", "Controllare parrucchiere_pref in database. Se disponibile, assegnarlo. Se no, chiedere al cliente se preferisce un altro operatore o aspettare."],
        ["Cliente nuovo", "Chiedere eta e tipo servizio. Usare le regole nel system prompt (da definire con Nadia)."],
        ["Cliente abituale indifferente", "Primo slot disponibile tra tutti gli operatori, ordinati per carico giornaliero."],
    ]
    story.append(make_table(["Caso", "Logica"], assign_rows, [usable*0.28, usable*0.72]))

    story.append(Paragraph("8.2 Servizi multipli", styles['SubSection']))
    story.append(Paragraph(
        "Se il cliente prenota piu servizi (es. Taglio + Barba = 60 min), il backend cerca 2 slot consecutivi liberi nello stesso calendario.",
        styles['BodyText2']
    ))

    story.append(Paragraph("8.3 Policy di cancellazione", styles['SubSection']))
    canc = [
        "Piu di 12 ore: cancellazione automatica, slot liberato, database aggiornato",
        "Meno di 12 ore: l'AI informa della policy, chiede conferma, segnala alla receptionist",
    ]
    for c in canc:
        story.append(bullet(c, styles))

    story.append(Paragraph("8.4 Anticipo prenotazione", styles['SubSection']))
    story.append(Paragraph(
        "Prenotazioni fino a 30 giorni in anticipo. Minimo 2 ore dal momento della prenotazione (default configurabile).",
        styles['BodyText2']
    ))

    story.append(Paragraph("8.5 Foto di riferimento", styles['SubSection']))
    story.append(Paragraph(
        "Quando il cliente invia una foto, il backend la scarica dal webhook WhatsApp Cloud API, salva l'URL nel database e conferma la ricezione.",
        styles['BodyText2']
    ))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 15-16: SEZIONE 9 — Deploy su Render
    # =========================================================================
    story.append(Paragraph("9. Deploy su Render", styles['SectionTitle']))

    story.append(Paragraph("9.1 Perche Render", styles['SubSection']))
    story.append(Paragraph("Render e una piattaforma PaaS (Platform as a Service) che elimina la necessita di gestire un server:", styles['BodyText2']))
    render_points = [
        "Piano gratuito per test: perfetto per sviluppo e demo, nessun costo iniziale",
        "Piano Starter (~7$/mese): istanza sempre attiva per produzione",
        "HTTPS automatico: certificato SSL incluso, nessuna configurazione",
        "Deploy da Git: ogni push su GitHub/GitLab avvia automaticamente il deploy",
        "Redis integrato: piano free da 25MB, sufficiente per le sessioni del salone",
        "PostgreSQL integrato: piano free da 1GB, sufficiente per il salone",
        "Log e metriche: dashboard integrata per monitoraggio",
        "Zero manutenzione: niente Docker, niente aggiornamenti OS, niente reverse proxy",
    ]
    for p in render_points:
        story.append(bullet(p, styles))

    story.append(Paragraph("9.2 Configurazione render.yaml", styles['SubSection']))
    story.append(Paragraph("File render.yaml nella root del progetto per Infrastructure as Code:", styles['BodyText2']))
    render_yaml = """services:
  - type: web
    name: salone-nadia-bot
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: META_WA_TOKEN
        sync: false
      - key: META_PHONE_NUMBER_ID
        sync: false
      - key: META_VERIFY_TOKEN
        sync: false
      - key: GOOGLE_CREDENTIALS_JSON
        sync: false
      - key: GCAL_SALONE_ID
        sync: false
      - key: GCAL_PARRUCCHIERE_IDS
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: salone-nadia-db
          property: connectionString
      - key: ADMIN_USERNAME
        sync: false
      - key: ADMIN_PASSWORD
        sync: false
      - key: SECRET_KEY
        sync: false
      - key: REDIS_URL
        fromService:
          name: salone-nadia-redis
          type: redis
          property: connectionString
      - key: SLOT_DURATION_MIN
        value: "30"
      - key: MAX_BOOKING_DAYS_AHEAD
        value: "30"
      - key: CANCEL_POLICY_HOURS
        value: "12"

  - type: redis
    name: salone-nadia-redis
    plan: free
    maxmemoryPolicy: allkeys-lru

databases:
  - name: salone-nadia-db
    plan: free"""
    story.append(Paragraph(render_yaml.replace('\n', '<br/>').replace('  ', '&nbsp;&nbsp;'), styles['CodeBlock']))

    story.append(Paragraph("9.3 Piani e limiti", styles['SubSection']))
    plan_rows = [
        ["Free (Web Service)", "0$", "Sleep dopo 15 min inattivita. Risveglio ~30-50 sec.", "Sviluppo e test"],
        ["Starter (Web Service)", "7$/mese", "Sempre attivo, 512MB RAM, HTTPS", "Produzione"],
        ["Free (Redis)", "0$", "25MB, connessioni limitate", "Sufficiente per il salone"],
        ["Starter (Redis)", "10$/mese", "256MB, piu connessioni", "Se servisse piu spazio"],
        ["Free (PostgreSQL)", "0$", "1GB, nessun limite di record", "Sufficiente per il salone"],
    ]
    story.append(make_table(["Piano", "Costo", "Caratteristiche", "Uso consigliato"], plan_rows, [usable*0.22, usable*0.12, usable*0.40, usable*0.26]))

    story.append(Paragraph("9.4 Procedura di deploy", styles['SubSection']))
    story.append(Paragraph("Il primo deploy richiede pochi passaggi:", styles['BodyText2']))
    deploy_steps = [
        "1. Crea un account su render.com e collega il repository GitHub",
        "2. Render rileva automaticamente il render.yaml e crea i servizi (incluso PostgreSQL)",
        "3. Vai in Dashboard > Environment e inserisci le variabili sensibili (API keys)",
        "4. Il deploy parte automaticamente. L'URL sara: https://salone-nadia-bot.onrender.com",
        "5. Configura questo URL come webhook in Meta for Developers",
        "6. Per aggiornare: fai git push e Render rideploya automaticamente",
    ]
    for s in deploy_steps:
        story.append(bullet(s, styles))

    story.append(Paragraph("9.5 Nota sul piano Free", styles['SubSection']))
    story.append(Paragraph(
        "Il piano gratuito mette in sleep l'istanza dopo 15 minuti di inattivita. Quando arriva un webhook, il servizio "
        "si risveglia in 30-50 secondi. Per la fase di test va bene. Per la produzione, il piano Starter a 7$/mese "
        "mantiene l'istanza sempre attiva con risposte immediate.",
        styles['BodyText2']
    ))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 17: SEZIONE 10 — Fasi di sviluppo
    # =========================================================================
    story.append(Paragraph("10. Fasi di sviluppo", styles['SectionTitle']))
    fasi_rows = [
        ["1", "Setup infrastruttura", "Account Render (free), repo GitHub, WhatsApp Cloud API Meta (app, webhook, token), PostgreSQL Render, Google Calendar API, credenziali Claude API", "2-3 gg"],
        ["2", "Backend core + prenotazione", "Progetto FastAPI, webhook WhatsApp, integrazione Claude, Google Calendar, creazione appuntamento, salvataggio PostgreSQL", "5-7 gg"],
        ["3", "Intake e CRM", "Raccolta dati cliente post-prenotazione. Storico cliente. Gestione foto. Pannello admin receptionist", "3-4 gg"],
        ["4", "Reminder e cancellazioni", "Job reminder 12h con APScheduler. Policy cancellazione. Notifica assenza. Template WhatsApp (sottomettere in Fase 1)", "3-4 gg"],
        ["5", "Test e go-live", "Test end-to-end con piano free Render. Affinamento system prompt. Passaggio a piano Starter. Training receptionist", "4-5 gg"],
        ["6", "Ricontatto inattivi", "Job schedulato ricontatto. Attivare solo dopo stabilita del sistema", "2-3 gg"],
    ]
    story.append(make_table(
        ["Fase", "Nome", "Attivita principali", "Stima"],
        fasi_rows,
        [usable*0.07, usable*0.18, usable*0.60, usable*0.15]
    ))
    story.append(Paragraph("Stima totale: 3-4 settimane lavorative.", styles['BodyText2']))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 18: SEZIONE 11 — Variabili configurazione
    # =========================================================================
    story.append(Paragraph("11. Variabili di configurazione", styles['SectionTitle']))
    story.append(Paragraph("Tutte le variabili vanno configurate nella sezione Environment di Render (mai nel codice):", styles['BodyText2']))
    var_rows = [
        ["ANTHROPIC_API_KEY", "sk-ant-...", "Claude API"],
        ["META_WA_TOKEN", "EAAx...", "WhatsApp Cloud API access token"],
        ["META_PHONE_NUMBER_ID", "123456789", "ID numero WhatsApp in Meta"],
        ["META_VERIFY_TOKEN", "mio_token_segreto", "Token verifica webhook"],
        ["GCAL_SALONE_ID", "salone@gmail.com", "Calendario eccezioni"],
        ["GCAL_PARRUCCHIERE_IDS", '[\"id1\",\"id2\"...]', "JSON array ID calendari"],
        ["GOOGLE_CREDENTIALS_JSON", "contenuto JSON", "Service account Google (su Render: come env var stringa)"],
        ["DATABASE_URL", "auto da render.yaml", "Connessione PostgreSQL (auto-configurata)"],
        ["ADMIN_USERNAME", "nadia", "Username pannello admin"],
        ["ADMIN_PASSWORD", "********", "Password pannello admin"],
        ["SECRET_KEY", "random_string", "Chiave per cookie di sessione"],
        ["REDIS_URL", "auto da render.yaml", "Connessione Redis (auto-configurata)"],
        ["SLOT_DURATION_MIN", "30", "Durata slot in minuti"],
        ["MAX_BOOKING_DAYS_AHEAD", "30", "Anticipo massimo prenotazione"],
        ["CANCEL_POLICY_HOURS", "12", "Ore minime cancellazione gratuita"],
        ["INACTIVITY_DAYS", "60", "Giorni inattivita per ricontatto"],
    ]
    story.append(make_table(
        ["Variabile", "Valore esempio", "Note"],
        var_rows,
        [usable*0.30, usable*0.28, usable*0.42]
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Su Render le credenziali Google vanno come stringa JSON nella variabile d'ambiente, non come file. Il config.py va adattato per leggere il JSON dalla variabile.",
        styles['BodyText2']
    ))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 19: SEZIONE 12 — Costi
    # =========================================================================
    story.append(Paragraph("12. Costi infrastruttura mensili stimati", styles['SectionTitle']))

    story.append(Paragraph("Fase di test (tutto gratuito)", styles['SubSection']))
    test_rows = [
        ["Render Web Service (Free)", "0$"],
        ["Render Redis (Free)", "0$"],
        ["WhatsApp Cloud API (test)", "0$ (numero test Meta)"],
        ["Claude API", "~qualche euro di test"],
        ["TOTALE TEST", "~0-5 EUR/mese"],
    ]
    story.append(make_table(["Voce", "Costo"], test_rows, [usable*0.55, usable*0.45]))

    story.append(Paragraph("Produzione", styles['SubSection']))
    prod_rows = [
        ["Render Web Service (Starter)", "~7$/mese (~6.50 EUR)", "Istanza sempre attiva"],
        ["Render Redis (Free)", "0$", "25MB sufficienti"],
        ["WhatsApp Cloud API", "5-15 EUR/mese", "Solo messaggi proattivi. Risposte gratuite"],
        ["Claude API (Sonnet)", "10-25 EUR/mese", "Salone piccolo"],
        ["PostgreSQL (Render Free)", "0$", "1GB, nessun limite record"],
        ["TOTALE PRODUZIONE", "~22-47 EUR/mese", ""],
    ]
    story.append(make_table(["Voce", "Costo stimato", "Note"], prod_rows, [usable*0.30, usable*0.25, usable*0.45]))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "<b>Nota:</b> Rispetto all'architettura originale con n8n + 360dialog + Airtable (~85-130 EUR/mese), il risparmio e del 60-80%. "
        "Se necessario, Redis Starter aggiunge ~10$/mese.",
        styles['BodyText2']
    ))
    story.append(PageBreak())

    # =========================================================================
    # PAGE 20: SEZIONE 13 — Note finali
    # =========================================================================
    story.append(Paragraph("13. Note finali e punti aperti", styles['SectionTitle']))

    story.append(Paragraph("13.1 Da definire con Nadia", styles['SubSection']))
    nadia_items = [
        "Regole specifiche di assegnazione parrucchiere per cliente nuovo",
        "Orario limite per l'AI: risponde 24/7 o solo durante l'orario del salone?",
        "Comportamento dell'AI fuori orario",
        "Nome del salone esatto per i template WhatsApp",
        "Anticipo minimo per prenotazione (varia per periodo?)",
    ]
    for n in nadia_items:
        story.append(bullet(n, styles))

    story.append(Paragraph("13.2 Rischi e mitigazioni", styles['SubSection']))
    risk_rows = [
        ["Approvazione template Meta lenta", "Sottomettere i template nella Fase 1"],
        ["Migrazione numero WhatsApp", "Verificare de-registrazione dall'app mobile prima di iniziare"],
        ["Google Calendar permessi", "Verificare condivisione calendari con service account API"],
        ["Costi API Claude", "Marginali per un salone piccolo. Monitorare nelle prime settimane"],
        ["Piano Free Render in sleep", "Accettabile per test. Passare a Starter per produzione"],
        ["Resistenza clienti abituali", "Comunicare la novita in anticipo. Mantenere opzione receptionist"],
    ]
    story.append(make_table(["Rischio", "Mitigazione"], risk_rows, [usable*0.35, usable*0.65]))

    story.append(Paragraph("13.3 Checklist pre-lancio", styles['SubSection']))
    checklist = [
        "PostgreSQL: database creato e migrazioni eseguite",
        "Pannello admin funzionante e testato",
        "WhatsApp: webhook configurato, template approvati",
        "Google Calendar: calendari creati, service account con accesso",
        "Claude API: system prompt affinato con test reali",
        "Render: variabili d'ambiente configurate, piano Starter attivato",
        "Test end-to-end completato con scenari reali",
    ]
    for c in checklist:
        story.append(bullet(c, styles))

    # Build the PDF
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    print(f"PDF generato con successo: {output_path}")

if __name__ == "__main__":
    build_pdf()
