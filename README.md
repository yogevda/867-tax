# 867.co.il — הוראות הפעלה

## מה יש בתיקייה זו
- `main.py` — כל הקוד של האתר
- `requirements.txt` — תלויות Python
- `render.yaml` — הגדרות לשרת

---

## שלב 1 — פתח חשבון Anthropic API (5 דקות)

1. כנס ל: https://console.anthropic.com
2. לחץ "Sign Up" — הרשם
3. לך ל "API Keys" → "Create Key"
4. שמור את המפתח (מתחיל ב-`sk-ant-...`)
5. לך ל "Billing" → הוסף כרטיס אשראי → הפקד $10

---

## שלב 2 — העלה לשרת Render (10 דקות)

1. כנס ל: https://render.com → Sign Up (חינם)
2. לחץ "New +" → "Web Service"
3. בחר "Deploy from existing code" → "Manual Deploy"
4. העלה את התיקייה הזו (drag & drop או ZIP)
5. בשדה **Environment Variable** הוסף:
   - Key: `ANTHROPIC_API_KEY`
   - Value: המפתח שקיבלת בשלב 1
6. לחץ "Create Web Service"

**זהו! Render יתן לך כתובת כמו: `https://867-tax.onrender.com`**

---

## שלב 3 — חבר את הדומיין 867.co.il (10 דקות)

1. היכנס לאתר שרכשת ממנו את הדומיין
2. עבור להגדרות DNS
3. הוסף רשומת CNAME:
   - Name: `@` או `www`
   - Value: הכתובת שקיבלת מ-Render
4. ב-Render: Settings → Custom Domains → הוסף `867.co.il`

---

## עלויות משוערות

| שירות | עלות |
|--------|------|
| Render (שרת) | חינם לתחילה |
| Anthropic API | ~$0.05 לניתוח (סנטים!) |
| דומיין | שילמת כבר |

---

## בעיות? שלח לי צילום מסך ואתקן.
