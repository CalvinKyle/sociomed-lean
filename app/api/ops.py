"""Small server-rendered owner console. No supplier access or external assets."""
import hmac
import secrets
from html import escape
from urllib.parse import parse_qs, urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.core import config
from app.core.rfq_status import RFQ_STATUSES
from app.models.db import get_db, RFQRequest
from app.data_access.procurement import get_rfq_line_items
from app.services import quote_workflow as workflow
from app.api.routes import LineEdit, ReviewActor, NamedActor, LPOReference
from pydantic import ValidationError

basic = HTTPBasic(auto_error=False)

def authenticate(credentials: HTTPBasicCredentials = Depends(basic)):
    if not config.API_KEY:
        raise HTTPException(503, 'Operations access is not configured')
    if not credentials or not hmac.compare_digest(credentials.password.encode(), config.API_KEY.encode()):
        raise HTTPException(401, 'Sign in with the API key as password', headers={'WWW-Authenticate': 'Basic realm="SocioMED operations"'})

router = APIRouter(prefix='/ops', dependencies=[Depends(authenticate)])

def e(value):
    return escape(str(value if value is not None else ''), quote=True)


def page(content, token):
    response = HTMLResponse('''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>SocioMED operations</title>
<style>body{font:18px system-ui;max-width:800px;margin:auto;padding:1rem;background:#f6faf9;color:#14332a}article,form{padding:1rem;margin:1rem 0;background:white;border:1px solid #cbd8d2;border-radius:8px}input,button,select{font:inherit;padding:.6rem;max-width:95%;margin:.3rem 0}label{display:block}button{background:#174e3c;color:white}a{color:#125a43}p{overflow-wrap:anywhere}</style></head><body><h1>SocioMED operations</h1><a href="/ops">RFQ queue</a>''' + content + '</body></html>')
    response.set_cookie('ops_csrf', token, httponly=True, samesite='strict', secure=config.PUBLIC_BASE_URL.startswith('https:'), max_age=1800, path='/ops')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


def form(rfq_id, action, token, body, label):
    return f'<form method="post" action="/ops/{rfq_id}/{action}"><input type="hidden" name="csrf" value="{e(token)}">{body}<button>{e(label)}</button></form>'


@router.get('', response_class=HTMLResponse)
def index(status: str = 'new', db=Depends(get_db)):
    content = '<nav>' + ' · '.join(f'<a href="/ops?status={s}">{s}</a>' for s in RFQ_STATUSES) + '</nav>'
    for r in db.query(RFQRequest).filter(RFQRequest.status == status).order_by(RFQRequest.created_at.desc()).limit(200):
        content += f'<article><a href="/ops/{r.id}">RFQ #{r.id}</a><p>{e(r.buyer_name)} · {e(r.organization)}</p><p>{e(r.product_name)} — {e(r.status)}</p></article>'
    return page(content, secrets.token_urlsafe(32))


@router.get('/{rfq_id}', response_class=HTMLResponse)
def detail(rfq_id: int, db=Depends(get_db)):
    r = workflow.get_rfq(db, rfq_id)
    token = secrets.token_urlsafe(32)
    content = f'<h2>RFQ #{r.id} — {e(r.status)}</h2>'
    for label, value in [('Buyer', r.buyer_name), ('Organisation', r.organization), ('Phone', r.phone), ('Delivery', r.delivery_location), ('Notes', r.notes), ('LPO', r.lpo_reference)]:
        content += f'<p><strong>{label}:</strong> {e(value)}</p>'
    for line in get_rfq_line_items(db, r.id):
        fields = f'<h3>{e(line.product_name)}</h3>'
        for name, value, kind in [('quantity', line.quantity, 'number'), ('uom', line.uom, 'text'), ('unit_price', line.unit_price, 'number')]:
            fields += f'<label>{e(name)} <input name="{name}" type="{kind}" value="{e(value)}" {"min=1" if kind == "number" else ""}></label>'
        content += form(r.id, f'line/{line.id}', token, fields, 'Save line')
    if r.equipment_review_required:
        content += '<p>Equipment review required. ' + e(r.technical_reviewed_by or 'Awaiting review') + '</p>'
        content += form(r.id, 'review', token, '<label>Reviewed by <input name="reviewed_by" required></label>', 'Technical review done')
    content += form(r.id, 'status', token, '<input type="hidden" name="status" value="quoted">', 'Mark quoted')
    content += form(r.id, 'approve', token, '<label>Approved by <input name="approved_by" required></label>', 'Approve')
    content += form(r.id, 'lpo', token, '<label>LPO reference <input name="lpo_reference" required></label>', 'Record LPO')
    for status in ['confirmed', 'fulfilled', 'cancelled', 'lost']:
        content += form(r.id, 'status', token, f'<input type="hidden" name="status" value="{status}">', status.title())
    return page(content, token)


def origin(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.netloc


@router.post('/{rfq_id}/{action:path}')
async def act(rfq_id: int, action: str, request: Request, db=Depends(get_db)):
    expected = origin(config.PUBLIC_BASE_URL or str(request.base_url))
    source = request.headers.get('origin') or request.headers.get('referer')
    if not source or origin(source) != expected:
        raise HTTPException(403, 'Same-origin form submission required')
    if 'application/x-www-form-urlencoded' not in request.headers.get('content-type', ''):
        raise HTTPException(415, 'Use the operations form')
    raw = await request.body()
    if len(raw) > 8192:
        raise HTTPException(413, 'Form too large')
    fields = {k: v[0] for k, v in parse_qs(raw.decode(), keep_blank_values=True).items()}
    token = fields.pop('csrf', '')
    cookie = request.cookies.get('ops_csrf', '')
    if not token or not cookie or not hmac.compare_digest(token.encode(), cookie.encode()):
        raise HTTPException(403, 'Invalid or expired form token; reload the RFQ')
    try:
        if action.startswith('line/'):
            values = LineEdit(quantity=fields.get('quantity'), uom=fields.get('uom'), unit_price=fields.get('unit_price') or None)
            workflow.edit_line(db, rfq_id, values.model_dump(exclude_unset=True), int(action.split('/')[1]))
        elif action == 'review':
            workflow.technical_review(db, rfq_id, ReviewActor(**fields).reviewed_by)
        elif action == 'approve':
            workflow.approve(db, [rfq_id], NamedActor(**fields).approved_by)
        elif action == 'lpo':
            workflow.issue_lpo(db, rfq_id, LPOReference(**fields).lpo_reference)
        elif action == 'status' and fields.get('status') in {'quoted', 'confirmed', 'fulfilled', 'cancelled', 'lost'}:
            r = workflow.set_status(db, rfq_id, fields['status'])
            from app.services.procurement import notify_buyer_of_status_change
            await notify_buyer_of_status_change(r)
        else:
            raise HTTPException(404, 'Unknown action')
    except (ValidationError, ValueError):
        raise HTTPException(422, 'Check the form values')
    return RedirectResponse(f'/ops/{rfq_id}', status_code=303)
