# SocioMed WhatsApp Marketplace — Lean Deployment Guide

**Stack:** Flask · Excel (pandas) · SQLite · fpdf2 · Meta Cloud API  
**Monthly cost:** UGX 0 (zero) until ~1,000 conversations/month  
**Deployment target:** Railway (recommended), Render, or any $5 VPS

---

## 1. What this does

A customer sends a WhatsApp message → your bot searches the Excel catalog → returns
an interactive product list → customer taps to add to cart → types `quote` → receives
a PDF quotation. No Odoo. No Redis. No database server.

---

## 2. Prerequisites

| What | Where | Cost |
|---|---|---|
| Meta Business Account + WhatsApp Business API | developers.facebook.com | Free |
| Railway account | railway.app | Free (hobby tier) |
| Google account (for Drive catalog updates) | google.com | Free |
| Your product catalog as `.xlsx` | See schema below | — |

---

## 3. Excel catalog setup

Create a file named `catalog.xlsx` with a sheet named `products`.

Required columns (column headers must match exactly):

```
product_id | name | category | sub_category | brand | sku | description
unit | currency | price_ugx | price_usd | stock_status | lead_days
min_order_qty | tags | related_ids | active
```

**stock_status values:** `IN_STOCK` / `ON_ORDER` / `OUT_OF_STOCK`  
**active:** `TRUE` or `FALSE`  
**related_ids:** comma-separated product_ids, e.g. `P-042,P-043`  
**tags:** comma-separated keywords for better search, e.g. `gloves,latex,examination,ppe`

### Example rows

| product_id | name | brand | price_ugx | stock_status | tags |
|---|---|---|---|---|---|
| P-001 | IV Cannula 20G | Becton | 1800 | IN_STOCK | iv,cannula,catheter,vein |
| P-002 | IV Cannula 22G | Becton | 1800 | IN_STOCK | iv,cannula,catheter |
| P-003 | Examination Gloves M (Box/100) | Ansell | 38000 | IN_STOCK | gloves,latex,examination,ppe |
| P-004 | ECG Machine 12-Lead | Contec | 1850000 | ON_ORDER | ecg,cardiac,monitor,machine |

---

## 4. Meta WhatsApp API setup

1. Go to https://developers.facebook.com → Create App → Business type
2. Add WhatsApp product
3. Under **API Setup**, note your:
   - `Phone Number ID` → `WHATSAPP_PHONE_ID`
   - Generate a **Permanent Token** → `WHATSAPP_TOKEN`
4. Under **Configuration → Webhook**:
   - Callback URL: `https://your-app.railway.app/webhook`
   - Verify Token: match what you set in `.env` as `VERIFY_TOKEN`
   - Subscribe to: `messages`

**Free tier:** 1,000 user-initiated conversations/month. Enough for launch.

---

## 5. Deploy to Railway

```bash
# 1. Install Railway CLI
npm install -g @railway/cli

# 2. Login
railway login

# 3. Create project
railway new sociomed-bot
cd your-repo-folder
railway link

# 4. Add environment variables (copy from .env.example)
railway variables set WHATSAPP_TOKEN=xxx
railway variables set WHATSAPP_PHONE_ID=xxx
railway variables set VERIFY_TOKEN=sociomed2025
# ... etc

# 5. Deploy
railway up

# 6. Get your URL
railway open
# Copy the URL → paste as Meta webhook callback
```

**Persistent storage:** Railway volumes persist between deploys.
Add a volume mount at `/app/data` in Railway dashboard to preserve SQLite + quotes.

---

## 6. Upload your catalog

### Option A: Direct upload (simplest)
```bash
# Via Railway CLI
railway volume cp catalog.xlsx /app/data/catalog.xlsx
```

### Option B: Endpoint (recommended for regular updates)
Add this route to bot.py for secure catalog updates:
```python
@app.route("/reload-catalog", methods=["POST"])
def reload_catalog():
    if request.headers.get("X-Admin-Key") != os.getenv("ADMIN_KEY"):
        return "Unauthorized", 401
    catalog.reload()
    return f"Reloaded: {len(catalog._df)} products"
```
Then update via:
```bash
curl -X POST https://your-app.railway.app/reload-catalog \
     -H "X-Admin-Key: your_secret"
```

The catalog auto-reloads every 30 minutes regardless.

---

## 7. Local development

```bash
git clone https://github.com/your-org/sociomed-lean
cd sociomed-lean

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and fill in your keys
cp .env.example .env

# Put your catalog in data/
mkdir -p data
cp your_catalog.xlsx data/catalog.xlsx

# Run
python -m app.bot

# Expose for Meta webhook (use ngrok for local dev)
ngrok http 5000
# → paste https://xxx.ngrok.io/webhook into Meta dashboard
```

---

## 8. Operations

### Monitor demand misses
```bash
sqlite3 data/sessions.db \
  "SELECT query, COUNT(*) as hits FROM demand_misses \
   GROUP BY query ORDER BY hits DESC LIMIT 20;"
```
These are products customers searched for but weren't in your catalog.
Add them to the Excel and reload. This is your sourcing intelligence.

### View active carts
```bash
sqlite3 data/sessions.db \
  "SELECT phone, name, qty, price_ugx FROM cart_items ORDER BY added_at DESC LIMIT 50;"
```

### Quotes log
All quotes are saved to `data/quotes/quotes_log.csv` and as individual PDFs in `data/quotes/`.

---

## 9. Scale path

When you outgrow free tier (>1k conversations/month or need CRM):

1. **Add Odoo back** — the `OdooConnector` from the original repo slots in as a data source. Keep Excel as fallback.
2. **Add Redis** — replace SQLite cart with Redis for horizontal scaling.
3. **Add Celery** — for async PDF generation at high volume.
4. **Upgrade WhatsApp tier** — Meta charges per conversation above free quota.

---

## 10. Realistic expectations

| Metric | Realistic range |
|---|---|
| Time to first live message | 1–3 days (Meta approval is the bottleneck) |
| Catalog items supported | Up to ~5,000 rows with good performance |
| Concurrent users handled | 50–100 (gunicorn 2 workers) |
| Quote-to-order conversion | 15–30% is realistic for B2B medical supplies |
| Catalog update lag | 0–30 minutes (auto-reload) |

The biggest friction in this market is **trust and follow-up speed**, not technology.
The bot's job is to qualify interest and generate the quote. Your sales team closes it.

---

## File structure

```
sociomed-lean/
├── app/
│   ├── bot.py          ← Flask app, routing, command handlers
│   ├── catalog.py      ← Excel search engine (hot-reloadable)
│   ├── cart.py         ← SQLite cart manager
│   ├── quote.py        ← PDF generator + Sheets logger
│   └── messenger.py    ← WhatsApp API wrapper
├── data/               ← Created at runtime (volume-mounted)
│   ├── catalog.xlsx    ← Your product catalog
│   ├── sessions.db     ← SQLite: carts + demand misses
│   └── quotes/         ← PDF quotes + CSV log
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```
