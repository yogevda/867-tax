"""האתר של יוגב דוד: מגיש את העמודים, ושולח למייל הסכמים חתומים ושאלות מהאתר."""
import os
import json
import base64
import urllib.request
import urllib.error
import ssl
import time
import smtplib
import hashlib
import html as htmlmod
import secrets
from datetime import datetime
from collections import defaultdict, deque
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(__file__).parent
PAGES = BASE / "pages"
MAIL_TO = os.environ.get("MAIL_TO", "yogevda@gmail.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAX_PDF_BYTES = 10 * 1024 * 1024
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "Yogev David Site <onboarding@resend.dev>")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


ROUTES = {
    "/": "index.html",
    "/forms": "forms.html",
    "/content": "content.html",
    "/ask": "ask.html",
    "/license": "license.html",
}


# ---------- מונה כניסות פשוט, בלי צד שלישי ----------
try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Asia/Jerusalem")
except Exception:  # pragma: no cover
    TZ = None
STATS_KEY = os.environ.get("STATS_KEY", "")
# רק טביעת אצבע של הסיסמה נשמרת בקוד, כך שאי אפשר לגלות אותה מהקוד עצמו
STATS_KEY_HASH = os.environ.get("STATS_KEY_HASH", "6641fdb4245b4a060f5085b9584e27dc9f54dd9e64d0e9828502b5b2bbdcaaf0")
PAGE_NAMES = {"/": "דף הבית", "/forms": "טפסים", "/content": "יצירת תוכן", "/ask": "שאלות", "/license": "רישיון"}
BOT_WORDS = ("bot", "crawl", "spider", "slurp", "preview", "facebookexternalhit", "whatsapp", "telegram", "headless",
             "python", "curl", "wget", "go-http", "render", "monitor", "uptime", "scan", "lighthouse")
STATS = {"since": None, "total": 0, "pages": defaultdict(int), "days": defaultdict(int), "visitors": set(), "recent": deque(maxlen=200)}
_SALT = secrets.token_hex(8)


def now_il():
    return datetime.now(TZ) if TZ else datetime.utcnow()


def record_visit(request: Request, path: str):
    ua = request.headers.get("user-agent", "")
    if not ua or any(w in ua.lower() for w in BOT_WORDS):
        return
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    who = hashlib.sha256((_SALT + ip + ua).encode()).hexdigest()[:10]  # מזהה אנונימי, בלי לשמור כתובת IP
    low = ua.lower()
    device = "טלפון" if ("mobile" in low or "android" in low or "iphone" in low) else ("טאבלט" if "ipad" in low else "מחשב")
    ref = request.headers.get("referer", "")
    src = ""
    if ref:
        host = ref.split("/")[2] if "//" in ref else ref
        if "867.co.il" not in host and "onrender.com" not in host:
            src = host.replace("www.", "")
    t = now_il()
    if STATS["since"] is None:
        STATS["since"] = t
    STATS["total"] += 1
    STATS["pages"][path] += 1
    STATS["days"][t.strftime("%d.%m")] += 1
    STATS["visitors"].add(who)
    STATS["recent"].appendleft((t.strftime("%d.%m %H:%M"), PAGE_NAMES.get(path, path), device, src or "ישירות", who[:4]))
    print(f"VISIT {t:%d.%m %H:%M} {path} {device} {src or '-'}", flush=True)


def page_handler(name, path):
    async def handler(request: Request):
        if request.method == "GET":
            try:
                record_visit(request, path)
            except Exception as e:  # המונה לעולם לא מפיל את האתר
                print("stats error:", e, flush=True)
        return FileResponse(PAGES / name, media_type="text/html; charset=utf-8")
    return handler


@app.get("/stats", include_in_schema=False)
async def stats(key: str = ""):
    ok = bool(STATS_KEY) and secrets.compare_digest(key, STATS_KEY)
    ok = ok or (bool(key) and secrets.compare_digest(hashlib.sha256(key.encode()).hexdigest(), STATS_KEY_HASH))
    if not ok:
        return RedirectResponse("/", status_code=302)
    e = htmlmod.escape
    since = STATS["since"].strftime("%d.%m.%Y %H:%M") if STATS["since"] else "עדיין אין כניסות"
    pages = "".join(f"<tr><td>{e(PAGE_NAMES.get(p, p))}</td><td>{n}</td></tr>" for p, n in sorted(STATS["pages"].items(), key=lambda x: -x[1]))
    days = "".join(f"<tr><td>{e(d)}</td><td>{n}</td></tr>" for d, n in list(STATS["days"].items())[::-1])
    recent = "".join(f"<tr><td>{e(a)}</td><td>{e(b)}</td><td>{e(c)}</td><td>{e(d)}</td><td>{e(v)}</td></tr>" for a, b, c, d, v in STATS["recent"])
    body = f"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>כניסות לאתר</title><style>
body{{font-family:Arial,sans-serif;background:#EEF3F8;color:#0F1F33;margin:0;padding:20px 16px;max-width:760px;margin:auto}}
h1{{font-size:24px;margin:0 0 4px}} .s{{color:#3F4A55;margin:0 0 18px}}
.k{{display:flex;gap:12px;flex-wrap:wrap;margin:0 0 20px}} .k div{{background:#fff;border:1px solid #CFDDEB;border-radius:12px;padding:12px 18px}} .k b{{display:block;font-size:28px}}
h2{{font-size:17px;margin:20px 0 8px}} table{{width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;font-size:15px}}
td{{padding:8px 10px;border-bottom:1px solid #E3EBF3}}</style></head><body>
<h1>כניסות לאתר</h1><p class="s">נספר מאז {e(since)}. רובוטים לא נספרים.</p>
<div class="k"><div><b>{STATS['total']}</b>צפיות בעמודים</div><div><b>{len(STATS['visitors'])}</b>מבקרים שונים</div></div>
<h2>לפי עמוד</h2><table>{pages}</table>
<h2>לפי יום</h2><table>{days}</table>
<h2>כניסות אחרונות</h2><table><tr><td><b>מתי</b></td><td><b>עמוד</b></td><td><b>מכשיר</b></td><td><b>הגיע מ</b></td><td><b>מבקר</b></td></tr>{recent}</table>
</body></html>"""
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


for path, name in ROUTES.items():
    app.add_api_route(path, page_handler(name, path), methods=["GET", "HEAD"], include_in_schema=False)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"ok": True}


@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": False}, status_code=404)
    return RedirectResponse("/", status_code=302)


# הגבלת קצב פשוטה לכל כתובת IP, כדי שלא ישלחו מאות מיילים
_hits = defaultdict(deque)


def rate_limit(request: Request, limit: int = 10, window: int = 3600):
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > window:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(status_code=429, detail="too many requests")
    q.append(now)


def clean(value: str, limit: int = 300) -> str:
    return " ".join((value or "").split())[:limit]


def send_via_resend(subject: str, body: str, reply_to: str, attachment: bytes, filename: str):
    """שליחה דרך Resend (HTTPS). עובד גם בתוכנית החינמית של Render, שחוסמת SMTP."""
    payload = {
        "from": RESEND_FROM,
        "to": [MAIL_TO],
        "subject": subject,
        "text": body,
    }
    if reply_to and "@" in reply_to and "\n" not in reply_to:
        payload["reply_to"] = reply_to
    if attachment:
        payload["attachments"] = [{"filename": filename, "content": base64.b64encode(attachment).decode("ascii")}]
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json", "User-Agent": "yogev-site/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 300:
                raise HTTPException(status_code=502, detail="mail failed")
    except urllib.error.HTTPError as e:
        print("Resend error:", e.code, e.read()[:500], flush=True)
        raise HTTPException(status_code=502, detail="mail failed")
    except urllib.error.URLError as e:
        print("Resend unreachable:", e, flush=True)
        raise HTTPException(status_code=502, detail="mail failed")


def send_mail(subject: str, body: str, reply_to: str = "", attachment: bytes = None, filename: str = ""):
    dump_dir = os.environ.get("MAIL_DUMP_DIR")  # לבדיקות מקומיות בלבד: שומר את המייל לקובץ במקום לשלוח
    if RESEND_API_KEY and not dump_dir:
        return send_via_resend(subject, body, reply_to, attachment, filename)
    if not dump_dir and not (SMTP_USER and SMTP_PASSWORD):
        raise HTTPException(status_code=503, detail="mail not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("האתר של יוגב דוד", SMTP_USER))
    msg["To"] = MAIL_TO
    if reply_to and "@" in reply_to and "\n" not in reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    if attachment:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=filename)
    if dump_dir:
        Path(dump_dir).mkdir(parents=True, exist_ok=True)
        (Path(dump_dir) / f"{int(time.time() * 1000)}.eml").write_bytes(bytes(msg))
        return
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=12) as server:
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


@app.post("/api/agreement")
async def agreement(
    request: Request,
    pdf: UploadFile = File(...),
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    level: str = Form(""),
    website: str = Form(""),
):
    if website:  # שדה מלכודת לבוטים
        return {"ok": True}
    rate_limit(request)
    data = await pdf.read(MAX_PDF_BYTES + 1)
    if len(data) > MAX_PDF_BYTES or not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="bad file")
    name, email, phone, level = clean(name, 120), clean(email, 200), clean(phone, 40), clean(level, 120)
    body = (
        "התקבל הסכם ייעוץ חתום מהאתר.\n\n"
        f"שם: {name}\nטלפון: {phone}\nאימייל: {email}\nרמת סיכון שאושרה: {level}\n\n"
        "ההסכם החתום מצורף כקובץ PDF."
    )
    safe = "".join(ch for ch in name if ch.isalnum() or ch in " -_")[:60].strip() or "לקוח"
    send_mail(f"הסכם ייעוץ חתום: {name or 'לקוח'}", body, reply_to=email, attachment=data, filename=f"הסכם ייעוץ - {safe}.pdf")
    return {"ok": True}


class Question(BaseModel):
    name: str = Field("", max_length=200)
    contact: str = Field("", max_length=200)
    question: str = Field("", max_length=5000)
    website: str = ""


@app.post("/api/question")
async def question(request: Request, q: Question):
    if q.website:
        return {"ok": True}
    if not (q.name.strip() and q.contact.strip() and q.question.strip()):
        raise HTTPException(status_code=400, detail="missing fields")
    rate_limit(request)
    body = f"שאלה חדשה מהאתר.\n\nשם: {clean(q.name, 120)}\nלחזור אל: {clean(q.contact, 200)}\n\n{q.question.strip()}"
    send_mail(f"שאלה מהאתר: {clean(q.name, 60)}", body, reply_to=q.contact.strip())
    return {"ok": True}
