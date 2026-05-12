"""
867.co.il - מערכת לעיבוד טפסי 867 והחזרי מס
"""

import os, json, base64, asyncio
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import anthropic
import tempfile

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ─────────────────────────────────────────────────────────────
# MAIN PAGE
# ─────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_PAGE

# ─────────────────────────────────────────────────────────────
# ANALYZE ENDPOINT
# ─────────────────────────────────────────────────────────────
@app.post("/analyze")
async def analyze(files: list[UploadFile] = File(...)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "API key לא מוגדר. הוסף ANTHROPIC_API_KEY.")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build message content with all PDFs
    content = []
    for f in files:
        data = await f.read()
        b64 = base64.b64encode(data).decode()
        content.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            "title": f.filename
        })

    content.append({
        "type": "text",
        "text": """אתה מומחה למיסוי בישראל. נתחת את כל הטפסים המצורפים (867 ו/או אישורי מס שבח).

עבור כל טופס 867 חלץ:
- שם הגוף המדווח (בנק/ברוקר)
- שנת המס
- רווחי הון חייבים (25%)
- הפסדים ברי קיזוז
- מס שנוכה במקור על ני"ע
- דיבידנד (25%) ומס שנוכה עליו
- ריבית (15%/25%) ומס שנוכה עליה
- שם המחזיק, ת.ז., חשבון בנק

עבור כל אישור מס שבח חלץ:
- מספר תיק מיסוי מקרקעין
- תאריך תשלום
- סכום ששולם

לאחר מכן חשב קיזוז הפסדים מצטבר בין שנים לפי סעיף 92 לפקודה:
1. קיזוז כנגד רווחי הון ני"ע
2. קיזוז כנגד דיבידנד וריבית (25%)
3. קיזוז כנגד שבח מקרקעין

ענה ONLY ב-JSON תקין בדיוק בפורמט הזה (ללא markdown):
{
  "taxpayer": {"name": "", "id": "", "bank": "", "branch": "", "account": ""},
  "years": [
    {
      "year": 2025,
      "source": "בנק הפועלים",
      "gains": 0,
      "losses": 0,
      "tax_sec": 0,
      "div": 0,
      "tax_div": 0,
      "int15": 0,
      "tax_int": 0,
      "int25": 0,
      "tax_int25": 0,
      "tax_shevach": 0,
      "shevach_tik": ""
    }
  ],
  "carryforward_calc": [
    {
      "year": 2025,
      "cf_in": 0,
      "avail": 0,
      "gains_after": 0,
      "div_after": 0,
      "shevach_gain": 0,
      "shevach_offset": 0,
      "shevach_refund": 0,
      "tax_due": 0,
      "withheld": 0,
      "refund": 0,
      "cf_out": 0
    }
  ],
  "total_refund": 0,
  "total_withheld": 0,
  "total_due": 0,
  "notes": ""
}"""
    })

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4000,
            messages=[{"role": "user", "content": content}]
        )
        text = resp.content[0].text.strip()
        # Clean any markdown fences
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip().rstrip("```").strip()
        result = json.loads(text)
        return JSONResponse(result)
    except json.JSONDecodeError as e:
        raise HTTPException(500, f"שגיאה בפענוח התגובה: {str(e)}")
    except Exception as e:
        raise HTTPException(500, f"שגיאה: {str(e)}")


# ─────────────────────────────────────────────────────────────
# PDF GENERATION ENDPOINT
# ─────────────────────────────────────────────────────────────
@app.post("/generate-pdf")
async def generate_pdf(data: dict):
    try:
        import subprocess, tempfile, os
        html = build_pdf_html(data)
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode='w', encoding='utf-8') as f:
            f.write(html)
            html_path = f.name
        pdf_path = html_path.replace(".html", ".pdf")
        subprocess.run(["wkhtmltopdf", "--encoding", "UTF-8",
                        "--page-size", "A4", "--margin-top", "10mm",
                        "--margin-bottom", "10mm", "--margin-right", "12mm",
                        "--margin-left", "12mm", "--disable-smart-shrinking",
                        html_path, pdf_path], check=True, capture_output=True)
        return FileResponse(pdf_path, media_type="application/pdf",
                           filename="דוח_867_מס.pdf")
    except Exception as e:
        raise HTTPException(500, f"שגיאת PDF: {str(e)}")


def build_pdf_html(data):
    tp = data.get("taxpayer", {})
    total_refund = data.get("total_refund", 0)
    total_withheld = data.get("total_withheld", 0)
    total_due = data.get("total_due", 0)
    calc = data.get("carryforward_calc", [])
    notes = data.get("notes", "")

    rows = ""
    for r in calc:
        rc = "color:#1b5e20" if r.get("refund",0) >= 0 else "color:#b71c1c"
        sign = "+" if r.get("refund",0) >= 0 else "−"
        sg = f'₪{abs(int(r.get("shevach_gain",0))):,}' if r.get("shevach_gain") else "—"
        rows += f"""<tr>
          <td style="font-weight:bold">{r.get('year','')}</td>
          <td>₪{abs(int(r.get('gains_after',0))):,}</td>
          <td style="color:#1565c0">{sg}</td>
          <td>₪{abs(int(r.get('withheld',0))):,}</td>
          <td>₪{abs(int(r.get('tax_due',0))):,}</td>
          <td style="{rc};font-weight:bold">{sign}₪{abs(int(r.get('refund',0))):,}</td>
          <td style="color:#e65100">₪{abs(int(r.get('cf_out',0))):,}</td>
        </tr>"""

    import datetime
    today = datetime.date.today().strftime('%d/%m/%Y')
    refund_color = "#1b5e20" if total_refund >= 0 else "#b71c1c"

    return f"""<!DOCTYPE html>
<html dir="rtl" lang="he"><head><meta charset="UTF-8">
<style>
* {{margin:0;padding:0;box-sizing:border-box}}
body {{font-family:Arial,sans-serif;font-size:9.5pt;direction:rtl;color:#1a1a2e}}
.header {{background:#1a237e;color:white;padding:16px 20px;margin-bottom:12px}}
.header h1 {{font-size:18pt;font-weight:bold}}
.sub {{font-size:8.5pt;opacity:.8;margin-top:3px}}
.result {{background:#e8f5e9;border:2px solid #2e7d32;border-radius:8px;padding:16px;margin:12px 0;display:flex;justify-content:space-between;align-items:center}}
.result .lbl {{font-size:11pt;font-weight:bold;color:{refund_color}}}
.result .amt {{font-size:26pt;font-weight:bold;color:{refund_color}}}
table {{width:100%;border-collapse:collapse;font-size:8.5pt;margin:8px 0}}
th {{background:#3949ab;color:white;padding:5px 8px;text-align:center}}
td {{padding:4px 8px;text-align:center;border-bottom:1px solid #f0f0f0}}
tr:nth-child(even) td {{background:#f8f9fa}}
.section {{border:1px solid #ddd;border-radius:6px;overflow:hidden;margin:10px 0}}
.stitle {{background:#283593;color:white;padding:6px 12px;font-weight:bold;font-size:9.5pt}}
.field-row {{display:flex;border-bottom:1px solid #eee;padding:5px 12px}}
.fl {{flex:1;color:#555;font-size:8.5pt}}
.fv {{font-weight:bold;font-size:9pt}}
.footer {{background:#1a237e;color:rgba(255,255,255,.7);text-align:center;padding:6px;font-size:7pt;margin-top:12px}}
.warn {{background:#fff8e1;border-right:4px solid #f57f17;padding:8px 12px;border-radius:4px;font-size:8pt;color:#555;margin:8px 0}}
</style></head><body>

<div class="header">
  <div style="display:flex;justify-content:space-between">
    <div><h1>{tp.get('name','')}</h1>
    <div class="sub">ת.ז. {tp.get('id','')} | {tp.get('bank','')} | סניף {tp.get('branch','')} | חשבון {tp.get('account','')}</div></div>
    <div style="text-align:left"><div style="font-size:13pt;font-weight:bold">סיכום מס 867</div>
    <div class="sub">הופק: {today} | 867.co.il</div></div>
  </div>
</div>

<div class="result">
  <div><div class="lbl">סך החזר מס משוער</div>
  <div style="font-size:8pt;color:#555;margin-top:4px">מס שנוכה/שולם: ₪{abs(int(total_withheld)):,} | מס לתשלום: ₪{abs(int(total_due)):,}</div></div>
  <div class="amt">₪{abs(int(total_refund)):,}</div>
</div>

<div class="section">
  <div class="stitle">קיזוז הפסדים בין שנים — נספח ג (טופס 1322)</div>
  <table>
    <thead><tr>
      <th>שנה</th><th>רווח נטו</th><th>שבח</th>
      <th>מס שנוכה</th><th>מס לתשלום</th><th>החזר/חוב</th><th>יתרת הפסד</th>
    </tr></thead>
    <tbody>{rows}
    <tr style="background:#1a237e;color:white;font-weight:bold">
      <td>סיכום</td><td>—</td><td>—</td>
      <td>₪{abs(int(total_withheld)):,}</td>
      <td>₪{abs(int(total_due)):,}</td>
      <td>+₪{abs(int(total_refund)):,}</td>
      <td>—</td>
    </tr></tbody>
  </table>
</div>

{"<div class='warn'>" + notes + "</div>" if notes else ""}

<div class="warn">מסמך זה הופק אוטומטית ומשמש לצורכי עזר בלבד. יש לאמת עם רואה חשבון לפני הגשה לרשות המסים.</div>
<div class="footer">867.co.il | מערכת אוטומטית לעיבוד טפסי 867 | סעיף 92 לפקודת מס הכנסה | {today}</div>
</body></html>"""


# ─────────────────────────────────────────────────────────────
# HTML PAGE
# ─────────────────────────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>867 — החזר מס חכם</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;700;800;900&display=swap" rel="stylesheet">
<style>
:root {
  --navy: #0f172a;
  --blue: #1e40af;
  --blue-light: #3b82f6;
  --green: #059669;
  --green-light: #d1fae5;
  --gold: #d97706;
  --bg: #f8fafc;
  --white: #ffffff;
  --gray: #64748b;
  --border: #e2e8f0;
  --text: #1e293b;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:'Heebo',sans-serif; background:var(--bg); color:var(--text); direction:rtl; min-height:100vh; }

/* NAV */
nav { background:var(--navy); padding:0 5%; display:flex; align-items:center; justify-content:space-between; height:60px; position:sticky; top:0; z-index:100; }
.logo { color:white; font-size:22px; font-weight:900; letter-spacing:-1px; }
.logo span { color:#60a5fa; }
.nav-badge { background:#1d4ed8; color:#93c5fd; font-size:11px; padding:3px 10px; border-radius:999px; }

/* HERO */
.hero { background:var(--navy); color:white; padding:60px 5% 80px; position:relative; overflow:hidden; }
.hero::before { content:''; position:absolute; inset:0; background:radial-gradient(ellipse at 20% 50%, rgba(59,130,246,0.15) 0%, transparent 60%); pointer-events:none; }
.hero-inner { max-width:800px; margin:0 auto; text-align:center; position:relative; }
.hero-badge { display:inline-block; background:rgba(96,165,250,0.15); border:1px solid rgba(96,165,250,0.3); color:#93c5fd; font-size:12px; padding:4px 14px; border-radius:999px; margin-bottom:20px; }
.hero h1 { font-size:clamp(32px,6vw,56px); font-weight:900; line-height:1.1; margin-bottom:16px; }
.hero h1 em { color:#60a5fa; font-style:normal; }
.hero p { font-size:17px; color:#94a3b8; line-height:1.7; max-width:560px; margin:0 auto 32px; }
.hero-stats { display:flex; gap:32px; justify-content:center; flex-wrap:wrap; }
.stat { text-align:center; }
.stat-num { font-size:28px; font-weight:800; color:#60a5fa; }
.stat-lbl { font-size:12px; color:#64748b; margin-top:2px; }

/* MAIN CARD */
.main { max-width:800px; margin:-40px auto 40px; padding:0 5%; position:relative; z-index:10; }
.card { background:var(--white); border-radius:16px; box-shadow:0 4px 40px rgba(0,0,0,0.08); overflow:hidden; }
.card-header { background:linear-gradient(135deg,#1e3a8a,#1d4ed8); color:white; padding:24px 28px; }
.card-header h2 { font-size:18px; font-weight:700; margin-bottom:4px; }
.card-header p { font-size:13px; opacity:.8; }
.card-body { padding:28px; }

/* UPLOAD ZONE */
.upload-zone { border:2px dashed var(--border); border-radius:12px; padding:40px 20px; text-align:center; cursor:pointer; transition:all 0.2s; background:#fafafa; }
.upload-zone:hover, .upload-zone.drag { border-color:var(--blue-light); background:#eff6ff; }
.upload-icon { font-size:40px; margin-bottom:12px; }
.upload-title { font-size:16px; font-weight:600; margin-bottom:6px; }
.upload-sub { font-size:13px; color:var(--gray); }
#fileInput { display:none; }

/* FILE LIST */
.file-list { display:flex; flex-direction:column; gap:8px; margin-top:16px; }
.file-chip { display:flex; align-items:center; gap:10px; background:#f1f5f9; border-radius:8px; padding:10px 14px; font-size:13px; }
.file-chip .fname { flex:1; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.file-chip .ftype { font-size:11px; color:var(--gray); background:#e2e8f0; padding:2px 7px; border-radius:999px; }
.file-chip .rm { cursor:pointer; color:var(--gray); font-size:18px; line-height:1; margin-right:auto; flex-shrink:0; }

/* BTN */
.btn { display:block; width:100%; padding:14px; background:var(--blue); color:white; border:none; border-radius:10px; font-size:15px; font-weight:700; cursor:pointer; margin-top:20px; font-family:'Heebo',sans-serif; transition:background 0.2s; }
.btn:hover:not(:disabled) { background:#1d4ed8; }
.btn:disabled { opacity:.5; cursor:not-allowed; }
.btn-green { background:var(--green); }
.btn-green:hover:not(:disabled) { background:#047857; }

/* STEPS */
.steps { display:flex; gap:0; margin-bottom:24px; }
.step { flex:1; display:flex; flex-direction:column; align-items:center; gap:6px; }
.step-num { width:32px; height:32px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:13px; font-weight:700; background:#e2e8f0; color:var(--gray); transition:all 0.3s; }
.step-num.active { background:var(--blue); color:white; }
.step-num.done { background:var(--green); color:white; }
.step-lbl { font-size:11px; color:var(--gray); text-align:center; }
.step-line { flex:1; height:2px; background:#e2e8f0; margin-top:16px; }
.step-line.done { background:var(--green); }

/* LOADER */
.loader { text-align:center; padding:40px; }
.spinner { width:48px; height:48px; border:4px solid #e2e8f0; border-top-color:var(--blue); border-radius:50%; animation:spin 0.8s linear infinite; margin:0 auto 16px; }
@keyframes spin { to { transform:rotate(360deg); } }
.loader-text { font-size:14px; color:var(--gray); }
.loader-sub { font-size:12px; color:#94a3b8; margin-top:4px; }

/* RESULTS */
.result-hero { background:linear-gradient(135deg,#064e3b,#059669); color:white; border-radius:12px; padding:24px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }
.result-hero .lbl { font-size:13px; opacity:.8; margin-bottom:4px; }
.result-hero .amount { font-size:36px; font-weight:900; }
.result-breakdown { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
.result-breakdown span { background:rgba(255,255,255,.15); border-radius:6px; padding:3px 10px; font-size:11px; }
.result-section { border:1px solid var(--border); border-radius:10px; overflow:hidden; margin-bottom:16px; }
.rs-title { background:#f1f5f9; padding:10px 16px; font-weight:600; font-size:13px; color:var(--navy); border-bottom:1px solid var(--border); }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th { background:#1e40af; color:white; padding:8px 10px; text-align:center; font-weight:600; font-size:11.5px; }
td { padding:7px 10px; text-align:center; border-bottom:1px solid #f1f5f9; }
tr:last-child td { border-bottom:none; }
tr:nth-child(even) td { background:#fafafa; }
.pos { color:#059669; font-weight:700; }
.neg { color:#dc2626; font-weight:700; }
.blue { color:#1d4ed8; font-weight:600; }
.orange { color:#d97706; }
.totals td { background:#0f172a !important; color:white !important; font-weight:700; }
.warn-box { background:#fffbeb; border:1px solid #fde68a; border-radius:8px; padding:12px 16px; font-size:12px; color:#92400e; line-height:1.7; margin-bottom:16px; }
.info-box { background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:12px 16px; font-size:12px; color:#1e40af; line-height:1.7; margin-bottom:16px; }

/* HOW IT WORKS */
.how { max-width:800px; margin:0 auto 60px; padding:0 5%; }
.how h2 { font-size:24px; font-weight:800; text-align:center; margin-bottom:32px; color:var(--navy); }
.how-steps { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:20px; }
.how-step { text-align:center; padding:24px 16px; background:white; border-radius:12px; box-shadow:0 2px 12px rgba(0,0,0,0.06); }
.how-step .icon { font-size:32px; margin-bottom:12px; }
.how-step h3 { font-size:14px; font-weight:700; margin-bottom:6px; color:var(--navy); }
.how-step p { font-size:12px; color:var(--gray); line-height:1.6; }

/* FOOTER */
footer { background:var(--navy); color:#475569; text-align:center; padding:24px; font-size:12px; }
footer a { color:#60a5fa; text-decoration:none; }

/* RESPONSIVE */
@media (max-width:600px) { .hero-stats { gap:20px; } .result-hero { flex-direction:column; } }

/* HIDDEN */
.hidden { display:none !important; }
</style>
</head>
<body>

<nav>
  <div class="logo">8<span>6</span>7<span style="color:#34d399;font-size:14px;font-weight:400;margin-right:4px">.co.il</span></div>
  <div class="nav-badge">בטא | חינם לתקופת הבדיקה</div>
</nav>

<div class="hero">
  <div class="hero-inner">
    <div class="hero-badge">✦ מופעל על ידי Claude AI</div>
    <h1>גלה כמה <em>כסף מגיע לך</em><br>בחזרה ממס הכנסה</h1>
    <p>העלה את טפסי 867 שלך מכל בית השקעות — המערכת תחשב אוטומטית את קיזוז ההפסדים ותכין דוח מוכן להגשה.</p>
    <div class="hero-stats">
      <div class="stat"><div class="stat-num">₪58K+</div><div class="stat-lbl">ממוצע החזר</div></div>
      <div class="stat"><div class="stat-num">7</div><div class="stat-lbl">שנים אחורה</div></div>
      <div class="stat"><div class="stat-num">2 דק'</div><div class="stat-lbl">עד לתוצאה</div></div>
      <div class="stat"><div class="stat-num">100%</div><div class="stat-lbl">אוטומטי</div></div>
    </div>
  </div>
</div>

<div class="main">
  <div class="card">
    <div class="card-header">
      <h2>העלאת מסמכים לניתוח</h2>
      <p>טפסי 867 + אישורי מס שבח (אם יש) | תומך בכל הבנקים ובתי ההשקעות</p>
    </div>
    <div class="card-body">

      <!-- STEPS -->
      <div class="steps">
        <div class="step">
          <div class="step-num active" id="s1">1</div>
          <div class="step-lbl">העלאת<br>מסמכים</div>
        </div>
        <div class="step-line" id="l1"></div>
        <div class="step">
          <div class="step-num" id="s2">2</div>
          <div class="step-lbl">ניתוח<br>AI</div>
        </div>
        <div class="step-line" id="l2"></div>
        <div class="step">
          <div class="step-num" id="s3">3</div>
          <div class="step-lbl">תוצאות<br>ודוח</div>
        </div>
      </div>

      <!-- UPLOAD SECTION -->
      <div id="uploadSection">
        <div class="upload-zone" id="dropZone" onclick="document.getElementById('fileInput').click()">
          <div class="upload-icon">📄</div>
          <div class="upload-title">גרור קבצים לכאן או לחץ לבחירה</div>
          <div class="upload-sub">טפסי 867 PDF + אישורי מס שבח | ניתן לבחור מספר קבצים בו-זמנית</div>
        </div>
        <input type="file" id="fileInput" accept="application/pdf" multiple>
        <div class="file-list" id="fileList"></div>
        <button class="btn" id="analyzeBtn" disabled onclick="analyze()">
          נתח את המסמכים שלי ←
        </button>
      </div>

      <!-- LOADER -->
      <div id="loaderSection" class="hidden">
        <div class="loader">
          <div class="spinner"></div>
          <div class="loader-text">Claude AI מנתח את המסמכים שלך...</div>
          <div class="loader-sub">מחלץ נתונים, מחשב קיזוז הפסדים בין שנים</div>
        </div>
      </div>

      <!-- RESULTS -->
      <div id="resultsSection" class="hidden"></div>

    </div>
  </div>
</div>

<!-- HOW IT WORKS -->
<div class="how">
  <h2>איך זה עובד?</h2>
  <div class="how-steps">
    <div class="how-step">
      <div class="icon">📤</div>
      <h3>מעלה את הטפסים</h3>
      <p>טפסי 867 מכל בית השקעות, עד 7 שנים אחורה</p>
    </div>
    <div class="how-step">
      <div class="icon">🤖</div>
      <h3>AI מנתח</h3>
      <p>Claude קורא את כל הטפסים ומחלץ את הנתונים הרלוונטיים</p>
    </div>
    <div class="how-step">
      <div class="icon">🔄</div>
      <h3>קיזוז חכם</h3>
      <p>חישוב קיזוז הפסדים מצטבר בין שנים לפי סעיף 92 לפקודה</p>
    </div>
    <div class="how-step">
      <div class="icon">📋</div>
      <h3>דוח מוכן</h3>
      <p>PDF מסכם מוכן להגשה למס הכנסה או לרואה חשבון</p>
    </div>
  </div>
</div>

<footer>
  <p>867.co.il | מערכת אוטומטית לעיבוד טפסי 867 ובקשות החזר מס</p>
  <p style="margin-top:6px">המידע באתר אינו מהווה ייעוץ מס. יש לאמת עם רואה חשבון לפני הגשה.</p>
</footer>

<script>
const files = [];

// DRAG & DROP
const dz = document.getElementById('dropZone');
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('drag'); });
dz.addEventListener('dragleave', () => dz.classList.remove('drag'));
dz.addEventListener('drop', e => { e.preventDefault(); dz.classList.remove('drag'); addFiles(e.dataTransfer.files); });
document.getElementById('fileInput').addEventListener('change', e => addFiles(e.target.files));

function addFiles(newFiles) {
  for (const f of newFiles) {
    if (f.type === 'application/pdf' && !files.find(x => x.name === f.name)) files.push(f);
  }
  renderFiles();
}

function removeFile(i) { files.splice(i,1); renderFiles(); }

function renderFiles() {
  const list = document.getElementById('fileList');
  list.innerHTML = files.map((f,i) => `
    <div class="file-chip">
      <span>📄</span>
      <span class="fname">${f.name}</span>
      <span class="ftype">${(f.size/1024).toFixed(0)} KB</span>
      <span class="rm" onclick="removeFile(${i})">×</span>
    </div>`).join('');
  document.getElementById('analyzeBtn').disabled = files.length === 0;
}

function setStep(n) {
  for (let i=1;i<=3;i++) {
    const el = document.getElementById('s'+i);
    el.className = 'step-num' + (i<n?' done':i===n?' active':'');
  }
  for (let i=1;i<=2;i++) {
    const el = document.getElementById('l'+i);
    el.className = 'step-line' + (i<n?' done':'');
  }
}

async function analyze() {
  document.getElementById('uploadSection').classList.add('hidden');
  document.getElementById('loaderSection').classList.remove('hidden');
  setStep(2);

  const fd = new FormData();
  files.forEach(f => fd.append('files', f));

  try {
    const res = await fetch('/analyze', { method:'POST', body:fd });
    if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
    const data = await res.json();
    showResults(data);
  } catch(err) {
    document.getElementById('loaderSection').classList.add('hidden');
    document.getElementById('uploadSection').classList.remove('hidden');
    setStep(1);
    alert('שגיאה: ' + err.message);
  }
}

function ils(v) { return '₪' + Math.abs(Math.round(v)).toLocaleString('he-IL'); }

function showResults(data) {
  document.getElementById('loaderSection').classList.add('hidden');
  setStep(3);
  document.getElementById('s3').className = 'step-num done';

  const tp = data.taxpayer || {};
  const calc = data.carryforward_calc || [];
  const total = data.total_refund || 0;
  const withheld = data.total_withheld || 0;
  const due = data.total_due || 0;
  const shevachTotal = calc.reduce((s,r) => s+(r.shevach_refund||0), 0);

  let rows = calc.map((r,i) => {
    const rc = (r.refund||0)>=0 ? 'pos' : 'neg';
    const sign = (r.refund||0)>=0 ? '+' : '−';
    const sg = r.shevach_gain ? `<span class="blue">${ils(r.shevach_gain)}</span>` : '—';
    return `<tr class="${i%2?'':''}">
      <td style="font-weight:700">${r.year}</td>
      <td>${ils(r.gains_after||0)}</td>
      <td>${sg}</td>
      <td>${ils(r.withheld||0)}</td>
      <td>${ils(r.tax_due||0)}</td>
      <td class="${rc}">${sign}${ils(r.refund||0)}</td>
      <td class="orange">${ils(r.cf_out||0)}</td>
    </tr>`;
  }).join('');

  const html = `
    <div class="result-hero">
      <div>
        <div class="lbl">סך החזר מס משוער</div>
        <div class="amount">${ils(total)}</div>
        <div class="result-breakdown">
          <span>מס שנוכה: ${ils(withheld)}</span>
          <span>מס לתשלום: ${ils(due)}</span>
          ${shevachTotal > 0 ? `<span>כולל החזר שבח: ${ils(shevachTotal)}</span>` : ''}
        </div>
      </div>
      <div style="text-align:left">
        <div style="font-size:12px;opacity:.7">${tp.name || ''}</div>
        <div style="font-size:11px;opacity:.6">${tp.bank||''} | חשבון ${tp.account||''}</div>
      </div>
    </div>

    <div class="result-section">
      <div class="rs-title">קיזוז הפסדים בין שנים — נספח ג (טופס 1322)</div>
      <table>
        <thead><tr>
          <th>שנה</th><th>רווח נטו</th><th>שבח</th>
          <th>מס שנוכה</th><th>מס לתשלום</th><th>החזר / חוב</th><th>יתרת הפסד</th>
        </tr></thead>
        <tbody>${rows}
        <tr class="totals">
          <td>סיכום</td><td>—</td><td>—</td>
          <td>${ils(withheld)}</td>
          <td>${ils(due)}</td>
          <td>+${ils(total)}</td>
          <td>—</td>
        </tr></tbody>
      </table>
    </div>

    <div class="info-box">
      <strong>הצעד הבא:</strong> הורד את הדוח המלא ועבד אותו לרואה חשבון, או הגש ישירות דרך אתר רשות המסים עם נספח ג (טופס 1322) + טפסי 867 המקוריים.
    </div>

    <div class="warn-box">
      ⚠️ מסמך זה הופק אוטומטית ומשמש לצורכי עזר בלבד. יש לאמת עם רואה חשבון לפני הגשה.
      ${data.notes ? '<br>' + data.notes : ''}
    </div>

    <button class="btn btn-green" onclick="downloadPDF(${JSON.stringify(JSON.stringify(data)).replace(/'/g,"\\'")})" style="margin-bottom:10px">
      הורד דוח PDF מלא ←
    </button>
    <button class="btn" style="background:#f1f5f9;color:#1e293b" onclick="location.reload()">
      ניתוח מסמכים חדשים
    </button>`;

  const rs = document.getElementById('resultsSection');
  rs.innerHTML = html;
  rs.classList.remove('hidden');
}

async function downloadPDF(dataStr) {
  try {
    const data = JSON.parse(dataStr);
    const res = await fetch('/generate-pdf', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(data)
    });
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'דוח_867_מס.pdf'; a.click();
  } catch(e) { alert('שגיאה בהורדת PDF: ' + e.message); }
}
</script>
</body>
</html>"""
