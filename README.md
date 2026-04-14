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
