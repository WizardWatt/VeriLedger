# VeriLedger

Real-time document integrity and fraud anomaly detection for bank underwriting, built for [hackathon name] under SBI's problem statement.

VeriLedger inspects a bank loan applicant's document bundle for forgery signals, cross-document contradictions, and coordinated fraud patterns — flagging suspicious submissions before they reach human underwriters.

## Architecture

The system is split into three independently runnable services:

| Service | Path | Stack | Responsibility |
|---|---|---|---|
| **Fraud Detection Engine** | `Graph_And_Velocity_Engine/` | FastAPI, SQLite, NetworkX | Forgery network graph, behavioral velocity rules, seal/stamp scoring, final risk verdicts |
| **OCR / Extraction Service** | `forensic/` | Flask, Ollama/Mistral | Document OCR, field extraction across 14 document schemas, image forensics (ELA, font consistency) |
| **Desktop Frontend** | `frontend/` | Electron | Upload workflow, dashboard, forgery graph visualization, history view |

The two backend services communicate over HTTP: the extraction service produces structured document data, which the fraud engine ingests via a dedicated adapter endpoint (`POST /ingest/ocr-output`) that reconciles schema differences between the two services.

### Fraud Detection Engine (`Graph_And_Velocity_Engine/`)

- **Forgery Network Graph** (`graph/forgery_graph.py`) — builds a graph of shared entities (names, addresses, phone numbers, bank accounts) across submitted documents to surface forgery rings and reused fake identities
- **Behavioral Velocity Engine** (`velocity/engine.py`) — cross-document consistency rules, including `PAYSLIP_ITR_CONTRADICTION` and `BANK_ROUND_TRIP` detection
- **Seal/Stamp Scorer** (`cv/seal_scorer.py`) — CV-based scoring of official seals and stamps for tampering
- **Persistence** (`db/store.py`) — WAL-mode SQLite with startup state restoration, so in-memory graph/velocity state survives a restart
- Exposes a FastAPI REST API (`api/main.py`) with endpoints for document ingestion, risk scoring, and the integration adapter

### OCR / Extraction Service (`forensic/`)

- Flask REST API (`app.py`, `routes/ocr_routes.py`)
- OCR and PDF handling (`services/ocr_service.py`, `services/pdf_service.py`)
- Image forensics: Error Level Analysis (`services/ela_service.py`), font consistency checks (`services/font_service.py`), seal/stamp detection (`services/seal_stamp_service.py`)
- Local LLM integration (`services/llm_service.py`) via Ollama/Mistral for plain-language extraction assistance, with a rule-based fallback so the service stays functional offline

### Frontend (`frontend/`)

Electron desktop app with dedicated views for upload, dashboard, velocity findings, forgery graph, and analysis history (`src/`).

## Running locally

Each service currently runs independently in its own environment — there is no shared build/orchestration step yet.

**Fraud Detection Engine**
```bash
cd Graph_And_Velocity_Engine
pip install -r requirements.txt   # if present in this directory
uvicorn api.main:app --reload
```

**OCR / Extraction Service**
```bash
cd forensic
pip install -r requirements.txt
python app.py
```

**Frontend**
```bash
cd frontend
npm install
npm start
```

> Note: the extraction service's LLM-assisted features require a local Ollama instance running the configured model (see `forensic/config.py`). Without it, extraction falls back to rule-based parsing only.

## Status

This is a hackathon build. Test coverage exists for the Fraud Detection Engine's core rules and API endpoints. The three services are not currently containerized or deployed — they run as local processes during development and demo.
