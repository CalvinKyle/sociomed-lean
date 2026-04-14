# SocioMed Lean – WhatsApp Marketplace

**WhatsApp-native procurement system for medical supplies** in Uganda and similar markets.

Healthcare providers search products, compare brands/prices, and request PFIs directly in WhatsApp.

## 🚀 Features
- Instant product search via WhatsApp
- Smart brand + price tier comparison
- PFI (quotation) requests with facility details
- Direct supplier WhatsApp notification
- Google Sheets as easy admin interface
- PostgreSQL + Redis for speed and scale

## 🧱 Architecture
WhatsApp Cloud API → FastAPI → PostgreSQL (core) + Redis (sessions/cache)  
Google Sheets → sync script → PostgreSQL (you still edit in Sheets)

## 📊 Data Model
(See Google Sheet tabs: products, vendors, inventory, pricing, aliases)

## ⚙️ Quick Start (Local)
```bash
pip install -r requirements.txt
python sync_sheets_to_db.py
uvicorn app.main:app --reload

## 🗃 Database Migrations (Alembic)
When you change models in `app/models/`:
```bash
alembic revision --autogenerate -m "Add new feature"
alembic upgrade head

## 🧵 Async Processing (Celery)
Webhook messages are offloaded to Celery tasks for scalability.
- Run locally: `celery -A app.core.celery_app worker --loglevel=info`
- Monitor: http://localhost:5555 (Flower dashboard)

