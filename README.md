# Indus Weave HR Pipeline

## One-Command Rebuild
    python run_pipeline.py

## Setup
    python -m venv .venv
    source .venv/Scripts/activate
    pip install -r requirements.txt
    python run_pipeline.py

## Structure
- data/raw/ — raw files
- ingestion/ — Stage 1
- transform/ — Stages 2-5
- warehouse/ddl/ — DDL
- analytics/ — 10 SQL + results CSVs
- quality/ — DQ
- presentation/ — CFO findings

## Team
- Saad
