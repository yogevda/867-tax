"""האתר של יוגב דוד: מגיש את העמודים, ושולח למייל הסכמים חתומים ושאלות מהאתר."""
import os
import ssl
import time
import smtplib
from collections import defaultdict, deque
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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


def page_handler(name):
    async def handler():
        return FileResponse(PAGES / name, media_type="text/html; charset=utf-8")
    return handler


for path, name in ROUTES.items():
    app.add_api_route(path, page_handler(name), methods=["GET", "HEAD"], include_in_schema=False)


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


def send_mail(subject: str, body: str, reply_to: str = "", attachment: bytes = None, filename: str = ""):
    dump_dir = os.environ.get("MAIL_DUMP_DIR")  # לבדיקות מקומיות בלבד: שומר את המייל לקובץ במקום לשלוח
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
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as server:
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
