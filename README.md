Provide an updated readme file by improving and adding to this where applicable: [# SocioMed WhatsApp Marketplace

A lightweight, WhatsApp-native procurement system for medical supplies in fragmented, price-sensitive markets.

## 🚀 Core Concept

This system enables healthcare providers to:

- Search for medical products via WhatsApp
- Compare market options (brand + price tiers)
- Request official quotations (PFIs)
- Connect directly with suppliers

## 🧱 Architecture

WhatsApp → FastAPI Backend → Google Sheets (DB)

## 📊 Data Model (Google Sheets)

### المنتجات (Sheets)

#### products
| product_id | name | category |

#### vendors
| vendor_id | name | phone |

#### inventory
| inventory_id | product_id | vendor_id | brand | stock_qty | lead_time_days |

#### pricing
| pricing_id | inventory_id | min_qty | max_qty | unit_price |

#### aliases
| alias | product_id |

---

## ⚙️ Setup

### 1. Clone Repo

```bash
git clone https://github.com/your-repo/sociomed-whatsapp-marketplace.git
cd sociomed-whatsapp-marketplace
]
