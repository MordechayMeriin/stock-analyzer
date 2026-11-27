<!-- Exported from the Claude Docs spec https://claude.ai/artifact/ENWaVsBC6dPkoZia3F8A4P on 2026-11-27. Diagrams are not included; see the original doc. -->

# איפיון טכני · דוח חברה (סכמת API + קליינט)

2026-11-27 · Yosi

## סקירה והיקף

הקליינט הוא מסך חברה אחד: רדאר של חמישה ציונים (1–10) לשלוש שנים, ציר אירועים ומספרים עיקריים, וכל הנתונים מגיעים ב-JSON אחד מהשרת. הקליינט רק מציג, ולא מחשב ציונים, כיוונים או צבעים.

**מה במסך (מלמעלה למטה)**

1. כותרת: לוגו, שם, טיקר, סקטור, תאריך הדוח האחרון ושורת סיכום אחת.
2. פרופיל החברה: רדאר עם בורר שנים (2023 | 2024 | 2025), עם ערך וחץ בקצה כל צלע.
3. ״למה כך?״: שורה לכל ציר, סגורה כברירת מחדל, ונפתחת לפירוט שנטען לפי דרישה.
4. אירועים: ציר של שלוש שנים.
5. מספרים עיקריים: עד שמונה מדדים של הסקטור עם שינוי שנתי.
6. שורת הבהרה: המידע תיאורי ואינו המלצה.

**החלטות עיצוב שננעלו**

- רדאר בשחור (shadcn Neutral), בלי כרטיסים, מסגרות, מקרא או נקודות צבעוניות.
- צבע מופיע רק בחצים (ירוק/אדום) ולא על המצולע. כל חץ מגובה בצורה: ▲ ▼ –.
- הכול בעברית ו-RTL. אנגלית כשפה נוספת בהמשך.
- טקסט ההסבר סגור כברירת מחדל.

**הנחות שדורשות אישור**

- הקליינט הוא אפליקציית web (PWA) בגישת mobile-first ב-React + TypeScript. אם זה native, הסכמה והלוגיקה נשארות ורק שכבת התצוגה משתנה.
- שלוש הקטגוריות שסוכמו עם השרת (יציבות, סיכון, פוטנציאל צמיחה) הן הליבה, והעיצוב מציג חמש: נוספו תמחור ואיכות תזרים. הסכמה תומכת ב-3 עד 8 צירים.

**מחוץ ל-MVP**

רשימת מעקב והתראות, השוואת מתחרים, דוחות רבעוניים, כרטיס שיתוף ומצב כהה.

## מסכים וניווט

האפליקציה היא שלושה מצבים במסלול אחד: חיפוש, טעינה, דוח. מהדוח חוזרים לחיפוש בלחיצה אחת, ואין תפריט או מסכים נוספים.

| מצב | מה רואים | יוצאים ממנו כש… |
|---|---|---|
| חיפוש (`/`) | שדה חיפוש אחד למניה או טיקר, עם השלמה אוטומטית מתחתיו | בוחרים הצעה, והמסך עובר לטעינה |
| טעינה | שם החברה והטיקר שנבחרו, ומחוון התקדמות עם שלבים (`fetching`, `analyzing`, `scoring`) | הדוח מוכן, או שיש שגיאה עם כפתור "נסה שוב" |
| דוח (`/c/:ticker`) | המסך הגדול: כותרת, רדאר, "למה כך?", ציר זמן, מספרי מפתח, disclaimer | לוחצים "נתח מניה חדשה", והמסך חוזר לחיפוש ריק |

**חיפוש**

- ההשלמה פונה ל-`GET /api/companies/search?q=` אחרי 2 תווים, עם השהיה של 250ms וביטול בקשה קודמת בהקלדה חדשה.
- כל הצעה מציגה שם, טיקר ובורסה. הצעות שהשרת מסמן כמנותחות (`tracked_ticker`) מופיעות ראשונות.
- חיפוש בעברית ובאנגלית, וגם לפי טיקר. אם אין תוצאות, שורה אחת: "לא מצאנו חברה בשם הזה".
- מקלדת: חצים לבחירה, Enter לאישור, ו-Escape לניקוי.

**טעינה**

- המסך נשאר פתוח עד שהדוח מוכן. אם הדוח כבר שמור, הוא קופץ ישר לדוח בלי להבהב.
- הכותרת של החברה נשארת על המסך בזמן ההמתנה, כדי שיהיה ברור מה נטען.

**חזרה**

- כפתור "נתח מניה חדשה" נמצא בראש מסך הדוח, ומחזיר ל-`/` עם שדה ריק ומקלדת פתוחה.
- כפתור "אחורה" של הדפדפן עובד אותו דבר, והדוח האחרון נשמר ב-cache של TanStack Query, כך שחזרה אליו מיידית.
- הכתובת `/c/:ticker` ניתנת לשיתוף, והיא פותחת ישר את הדוח (או את הטעינה). הנתיב `/:ticker` תפוס היום בדפדפן הקיים בריפו, ולכן הדוח יושב תחת `/c/`.

## API וזרימת נתונים

שלוש נקודות קצה מספיקות ל-MVP, והדוח המלא של שלוש השנים חוזר בקריאה אחת, כך שבורר השנים עובד בלי רשת.

| Method | נתיב | מטרה | הערות |
|---|---|---|---|
| GET | `/api/companies/search?q=` | חיפוש לפי טיקר או שם | קיים בריפו (CompanySearchHit): שם, טיקר, ISIN; לוגו חסר |
| GET | `/api/companies/{ticker}/report?mode=cached` | הדוח המלא: כותרת, ציונים ל-3 שנים, אירועים, מספרים | 200 מוכן, 202 בעיבוד |
| GET | `/api/companies/{ticker}/report/axes/{axisId}?year=2025` | פירוט של ציר אחד | נטען רק כשפותחים שורה |

**כללים**

- הדוח בלתי-משתנה לפי `reportId`: השרת מחזיר `ETag` ו-`Cache-Control: public, max-age=300, stale-while-revalidate=86400`.
- `locale` קובע את כל הטקסטים (תוויות, סיכום, אירועים). מזהים (`id`, `type`) יציבים ולא מתורגמים.
- שדות חדשים נוספים באותה גרסה מג׳ורית, והקליינט מתעלם משדות לא מוכרים. שינוי שובר הוא `schemaVersion` חדש.
- שגיאות בפורמט `application/problem+json` (RFC 9457).

**עיבוד איטי**

אם הניתוח לא מוכן, השרת משדר אירועי SSE באותו מנגנון שבו עובד ה-OSINT הקיים: `progress` עם שלב ואחוזים, `done` עם הדוח המלא, ו-`error` עם `{code, message}`. הקליינט משתמש ב-`web/src/api/sse.ts` הקיים, ולא ב-polling. אם הדוח כבר שמור, התשובה היא בקשת JSON רגילה עם 200.

> _[תרשים: זרימת טעינת דוח · שמור מול SSE] (מופיע במסמך המקורי)_

דוח שמור חוזר ב-200 ופותח את המסך מיד. אחרת הקליינט מאזין ל-SSE עד `done`, ו-`error` מוביל למסך שגיאה.

## סכמת JSON

הדוח הוא אובייקט אחד עם שבעה חלקים: `company`, `report`, `summary`, `profile`, `events`, `keyMetrics`, `warnings`. אלה ההחלטות שמעצבות אותו:

- **כל השנים בקריאה אחת.** `profile.axes[].scores` מחזיק ציון לכל שנה, ולכן בורר השנים הוא החלפת שנה בצד הלקוח.
- **תמיד ״גבוה = טוב״.** ציר הסיכון שסוכם (1–10, גבוה = מסוכן) נשלח כ-`safety`, כלומר 11 פחות הסיכון, כדי שכל הרדאר ייקרא באותו כיוון.
- **השרת מחליט על המשמעות.** `trend.direction` קובע את צורת החץ ו-`trend.tone` את הצבע (`positive` ירוק, `negative` אדום, `neutral` אפור). בחוב נטו שעולה החץ עולה והטון שלילי.
- **מספר הצירים דינמי** (3 עד 8), בסדר קבוע שהשרת קובע. מזהים יציבים: `stability`, `safety`, `growth`, `valuation`, `cash_quality`.
- **ערך חסר הוא ****`null`**, עם `status: "insufficient_data"` על הציר. אף פעם לא 0.

**שמות שדות.** החוזה כתוב ב-snake_case, כמו ה-API הקיים, והקליינט משתמש בהם כמו שהם. כל שם ב-camelCase במקום אחר במסמך (בטבלת המיפוי ובטיפוסים) הוא שם ישן, ומתרגמים אותו ל-snake_case (`fiscalYear` הופך ל-`fiscal_year`). סכמת האמת היא `openapi.json`, והדוגמה כאן מדוגמה בלבד. סכומים בכסף נשלחים כמחרוזת עשרונית, כמו בשאר ה-API.

**דוגמה** (מקוצרת: 2 מתוך 5 צירים, 2 אירועים, 2 מספרים)

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-03-30T09:30:00Z",
  "mode": "cached",
  "company": {
    "ticker": "MLTM",
    "name_he": "מלם תים",
    "name_en": "Malam-Team Ltd.",
    "logo_url": null,
    "exchange": "TASE",
    "currency": "ILS",
    "sector": { "id": "software", "name": "תוכנה ושירותי IT" }
  },
  "report": {
    "type": "annual",
    "fiscal_year": 2025,
    "period_end": "2025-12-31",
    "published_at": "2026-03-25"
  },
  "summary": { "text": "צמיחה חזקה ותזרים יציבים, אבל החוב גדל." },
  "years": [2023, 2024, 2025],
  "profile": {
    "axes": [
      {
        "id": "stability",
        "label": "יציבות",
        "status": "ok",
        "detail_url": "/api/companies/MLTM/report/axes/stability",
        "scores": [
          { "fiscal_year": 2023, "value": 6, "sector_median": 6, "trend": null, "driver": null },
          { "fiscal_year": 2024, "value": 6, "sector_median": 6,
            "trend": { "direction": "flat", "delta": 0, "tone": "neutral" },
            "driver": { "label": "מרווח יציב", "tone": "neutral" } },
          { "fiscal_year": 2025, "value": 7, "sector_median": 6,
            "trend": { "direction": "up", "delta": 1, "tone": "positive" },
            "driver": { "label": "מרווח תפעולי עולה", "tone": "positive" } }
        ]
      },
      {
        "id": "safety",
        "label": "ביטחון",
        "status": "ok",
        "detail_url": "/api/companies/MLTM/report/axes/safety",
        "scores": [
          { "fiscal_year": 2023, "value": 7, "sector_median": 6, "trend": null, "driver": null },
          { "fiscal_year": 2024, "value": 6, "sector_median": 6,
            "trend": { "direction": "down", "delta": -1, "tone": "negative" },
            "driver": { "label": "מינוף עולה", "tone": "negative" } },
          { "fiscal_year": 2025, "value": 5, "sector_median": 6,
            "trend": { "direction": "down", "delta": -1, "tone": "negative" },
            "driver": { "label": "חוב נטו גדל", "tone": "negative" } }
        ]
      }
    ]
  },
  "events": [
    { "id": "ev-20260325-report", "date": "2026-03-25", "date_precision": "day",
      "type": "report", "title": "דוח שנתי 2025", "summary": "עלייה בהכנסות",
      "importance": 3, "tone": "positive", "source_url": null },
    { "id": "ev-202509-credit", "date": "2025-09", "date_precision": "month",
      "type": "financing", "title": "גיוס אג״ח", "summary": "גיוס חוב למימון רכישה",
      "importance": 2, "tone": "neutral", "source_url": "https://example.com/news/1" }
  ],
  "key_metrics": [
    { "id": "revenue", "label": "הכנסות", "format": "currency", "currency": "ILS",
      "series": [ { "fiscal_year": 2023, "value": "3500000000" }, { "fiscal_year": 2024, "value": "3750000000" }, { "fiscal_year": 2025, "value": "4200000000" } ],
      "change": { "direction": "up", "pct": 12, "tone": "positive" } },
    { "id": "net_debt", "label": "חוב נטו", "format": "currency", "currency": "ILS",
      "series": [ { "fiscal_year": 2023, "value": "800000000" }, { "fiscal_year": 2024, "value": "960000000" }, { "fiscal_year": 2025, "value": "1100000000" } ],
      "change": { "direction": "up", "pct": 15, "tone": "negative" } }
  ],
  "warnings": []
}
```

**JSON Schema (draft 2020-12)**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "CompanyReport",
  "type": "object",
  "required": ["schema_version", "generated_at", "mode", "company", "report", "years", "profile", "events", "key_metrics"],
  "properties": {
    "schema_version": { "type": "string", "pattern": "^1\\.\\d+$" },
    "generated_at": { "type": "string", "format": "date-time" },
    "mode": { "enum": ["cached", "live"] },
    "company": { "$ref": "#/$defs/company" },
    "report": { "$ref": "#/$defs/report" },
    "summary": { "type": "object", "required": ["text"], "properties": { "text": { "type": "string", "maxLength": 160 } } },
    "years": { "type": "array", "minItems": 1, "maxItems": 3, "items": { "type": "integer" } },
    "profile": { "type": "object", "required": ["axes"], "properties": { "axes": { "type": "array", "minItems": 3, "maxItems": 8, "items": { "$ref": "#/$defs/axis" } } } },
    "events": { "type": "array", "maxItems": 30, "items": { "$ref": "#/$defs/event" } },
    "key_metrics": { "type": "array", "maxItems": 8, "items": { "$ref": "#/$defs/metric" } },
    "warnings": { "type": "array", "items": { "$ref": "#/$defs/warning" } }
  },
  "$defs": {
    "tone": { "enum": ["positive", "negative", "neutral"] },
    "direction": { "enum": ["up", "down", "flat"] },
    "company": {
      "type": "object",
      "required": ["ticker", "name_he", "currency", "sector"],
      "properties": {
        "ticker": { "type": "string" },
        "name_he": { "type": "string" },
        "name_en": { "type": ["string", "null"] },
        "logo_url": { "type": ["string", "null"], "format": "uri" },
        "exchange": { "type": "string" },
        "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
        "sector": { "type": "object", "required": ["id", "name"], "properties": { "id": { "type": "string" }, "name": { "type": "string" } } }
      }
    },
    "report": {
      "type": "object",
      "required": ["type", "fiscal_year", "period_end", "published_at"],
      "properties": {
        "type": { "const": "annual" },
        "fiscal_year": { "type": "integer" },
        "period_end": { "type": "string", "format": "date" },
        "published_at": { "type": "string", "format": "date" }
      }
    },
    "axis": {
      "type": "object",
      "required": ["id", "label", "status", "scores"],
      "properties": {
        "id": { "type": "string" },
        "label": { "type": "string", "maxLength": 16 },
        "status": { "enum": ["ok", "insufficient_data"] },
        "detail_url": { "type": "string" },
        "scores": { "type": "array", "minItems": 1, "maxItems": 3, "items": { "$ref": "#/$defs/score" } }
      }
    },
    "score": {
      "type": "object",
      "required": ["fiscal_year", "value"],
      "properties": {
        "fiscal_year": { "type": "integer" },
        "value": { "type": ["integer", "null"], "minimum": 1, "maximum": 10 },
        "sector_median": { "type": ["number", "null"], "minimum": 1, "maximum": 10 },
        "trend": {
          "type": ["object", "null"],
          "required": ["direction", "tone"],
          "properties": { "direction": { "$ref": "#/$defs/direction" }, "delta": { "type": "number" }, "tone": { "$ref": "#/$defs/tone" } }
        },
        "driver": {
          "type": ["object", "null"],
          "required": ["label", "tone"],
          "properties": { "label": { "type": "string", "maxLength": 28 }, "tone": { "$ref": "#/$defs/tone" } }
        }
      }
    },
    "event": {
      "type": "object",
      "required": ["id", "date", "date_precision", "type", "title", "importance"],
      "properties": {
        "id": { "type": "string" },
        "date": { "type": "string", "pattern": "^\\d{4}-\\d{2}(-\\d{2})?$" },
        "date_precision": { "enum": ["day", "month"] },
        "type": { "enum": ["report", "acquisition", "leadership", "guidance", "financing", "legal", "regulatory", "buyback", "insider", "other"] },
        "title": { "type": "string", "maxLength": 40 },
        "summary": { "type": "string", "maxLength": 80 },
        "importance": { "type": "integer", "minimum": 1, "maximum": 3 },
        "tone": { "$ref": "#/$defs/tone" },
        "source_url": { "type": ["string", "null"], "format": "uri" }
      }
    },
    "metric": {
      "type": "object",
      "required": ["id", "label", "format", "series"],
      "properties": {
        "id": { "type": "string" },
        "label": { "type": "string" },
        "format": { "enum": ["currency", "percent", "ratio", "count"] },
        "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
        "series": { "type": "array", "minItems": 1, "maxItems": 3, "items": { "type": "object", "required": ["fiscal_year", "value"], "properties": { "fiscal_year": { "type": "integer" }, "value": { "type": ["string", "null"], "description": "decimal string, as in the rest of the API" } } } },
        "change": { "type": ["object", "null"], "required": ["direction", "tone"], "properties": { "direction": { "$ref": "#/$defs/direction" }, "pct": { "type": "number" }, "tone": { "$ref": "#/$defs/tone" } } }
      }
    },
    "warning": {
      "type": "object",
      "required": ["code", "message"],
      "properties": { "code": { "type": "string" }, "message": { "type": "string" } }
    }
  }
}
```

**פירוט ציר** (`GET .../axes/{axisId}?year=2025`, נטען כשפותחים שורה)

```json
{
  "axisId": "safety",
  "fiscalYear": 2025,
  "headline": "החוב הנקי עלה מהר יותר מהרווח התפעולי",
  "factors": [
    { "label": "חוב נטו ל-EBITDA", "display": "1.2x", "tone": "negative" },
    { "label": "כיסוי ריבית", "display": "9.4x", "tone": "neutral" }
  ],
  "sectorComparison": { "position": "below", "median": 6 },
  "text": "פסקה קצרה של עד 600 תווים שמסבירה את הציון."
}
```

בסכמה הזו `headline` עד 80 תווים, `factors` עד 5, `position` הוא אחד מ-`above`, `below`, `equal`, ו-`text` טקסט רגיל בלי markdown.

## מצבים, טעינה ושגיאות

לכל מצב יש אות יחיד בתגובה ותצוגה מוגדרת. הקליינט לא מציג מסך ריק ולא מציג 0 במקום נתון חסר.

| מצב | איך מזהים | מה מוצג |
|---|---|---|
| טעינה ראשונה | אין נתונים בקאש | שלד אפור: כותרת, מסגרת רדאר ריקה, חמש שורות |
| עיבוד | `202` או `status: "processing"` | שם וטיקר (מהחיפוש), מסגרת רדאר, הודעת ״מנתחים את הדוח״, polling |
| ציר בלי נתונים | `status: "insufficient_data"` או `value: null` | נקודה חלולה במקום קודקוד, ״אין מספיק נתונים״ בשורה, בלי חץ |
| פחות מ-3 צירים תקינים | פחות משלושה עם `value` | בלי רדאר, רק הרשימה ״למה כך?״ |
| פחות מ-3 שנים | `years.length < 3` | בורר שנים עם מה שיש; שנה אחת = בלי בורר |
| השנה הראשונה | `trend: null` | ערך בלי חץ |
| בלי לוגו | `logoUrl: null` או כשל טעינה | ריבוע עם האות הראשונה של השם |
| בלי אירועים | `events: []` | הסעיף מוסתר |
| מספר חסר | `value: null` בסדרה | ״—״ בתא, בלי שינוי |
| דוח ישן | `warnings[].code = "stale_report"` | שורת ״נכון ל-[תאריך]״ בצבע מושתק |
| חברה לא נמצאה | `404` | ״לא מצאנו את הטיקר״ + שדה חיפוש |
| חברה לא נתמכת | `422`, `code: "unsupported_company"` | הסבר קצר (למשל: אין דוח שנתי מלא) |
| הגבלת קצב | `429` + `Retry-After` | ״עומס, נסו שוב בעוד X שניות״ וניסיון אוטומטי אחד |
| רשת או 5xx | כשל בקריאה | הודעה וכפתור ״נסו שוב״. אם יש קאש, מציגים אותו עם ״נכון ל-...״ |

**גוף 202 (עיבוד)**

```json
{
  "status": "processing",
  "reportId": "NWSY-FY2025-r4",
  "progress": { "stage": "analyzing", "percent": 40 },
  "retryAfterSec": 2
}
```

ערכי `stage` (`queued`, `fetching`, `analyzing`, `scoring`) משמשים רק להודעה, ואין להסתמך על סדרם.

**גוף שגיאה (4xx/5xx)**

```json
{
  "type": "https://api.example.com/problems/unsupported-company",
  "title": "החברה אינה נתמכת",
  "status": 422,
  "code": "unsupported_company",
  "detail": "לא נמצא דוח שנתי מלא ל-ABCD."
}
```

הקליינט מתרגם לפי `code` לטקסט מקומי, ולא מציג את `detail` ישירות.

## ארכיטקטורת הקליינט

השרת הוא מקור האמת, והקליינט מאמת את התשובה, ממיר אותה למודל תצוגה ומצייר. זה הסטאק המומלץ:

| שכבה | בחירה | למה |
|---|---|---|
| Build | Vite + React 19 + TypeScript (strict) | מהיר, פשוט, PWA קל |
| UI | shadcn/ui (Radix) + Tailwind v4 | הטוקנים של Neutral, הקוד בבעלותנו |
| נתונים | TanStack Query v5 | קאש, retry, polling דרך `refetchInterval` |
| אימות | Zod | מאמת את התשובה בגבול הרשת, והטיפוסים נגזרים ממנו |
| ניווט | React Router | `/c/:ticker?y=2025` |
| i18n | react-i18next + Intl | עברית, RTL, פורמט תאריכים ומספרים |
| גרף | קומפוננטת SVG משלנו | תוויות עם חצים וגיאומטריה קבועה, בלי Recharts |
| בדיקות | Vitest, Testing Library, MSW, Playwright | ראו סעיף בדיקות |

**מבנה תיקיות**

```text
src/
  api/
    client.ts        fetch + טיפול בשגיאות problem+json
    schema.ts        Zod schema = הסכמה בסעיף הקודם
    queries.ts       useReport, useAxisDetail, useSearch
  features/report/
    ReportPage.tsx
    toReportView.ts  פונקציה טהורה: report + year -> view model
    components/
      CompanyHeader.tsx
      ProfileRadar/    RadarChart.tsx, geometry.ts, YearTabs.tsx
      ScoreList/       ScoreRow.tsx, AxisDetail.tsx
      EventsTimeline.tsx
      KeyMetrics.tsx
      Disclaimer.tsx
  components/ui/     shadcn
  lib/               format.ts (תאריכים, מטבע), i18n.ts
  mocks/             fixtures + MSW handlers
```

**זרימת נתונים**

1. `useReport(ticker)` קורא ל-API, מאמת ב-Zod ושומר בקאש (`staleTime` 5 דקות). במצב `processing` הוא שואל שוב לפי `retryAfterSec`.
2. `toReportView(report, year)` מחזיר את מה שהמסך צריך לשנה שנבחרה: צירים, חצים, שורות, אירועים מסוננים.
3. הרכיבים מקבלים props בלבד ולא גושים לרשת. היחידה היא `AxisDetail`, שטוען את הפירוט כשפותחים שורה.

> _[תרשים: היררכיית רכיבים · מסך החברה] (מופיע במסמך המקורי)_

`CompanyPage` מחזיק את השנה הנבחרת, וכל רכיב קורא את החלק שלו מ-`useReport`. רק `AxisDetail` פונה לשרת בנפרד.

**סטייט**

- טיקר ושנה חיים ב-URL, כך שקישור משתף פותח אותו מסך בדיוק.
- סטייט מקומי רק למה פתוח (שורות מורחבות). אין store גלובלי.
- כשל Zod הוא שגיאה כללית עם רישום של `reportId` בלוג. הקליינט לא מנסה לתקן נתונים.
- קאש נשמר ב-IndexedDB לעבודה בלי רשת, עם ״נכון ל-...״ במסך.

**חוזה הגרף**

הרדאר הוא רכיב תצוגה טהור שלא מבין את הסכמה:

```ts
type RadarAxis = {
  id: string;
  label: string;
  value: number | null; // 1-10, null = אין נתונים
  trend: { direction: 'up' | 'down' | 'flat'; tone: 'positive' | 'negative' | 'neutral' } | null;
};

type RadarChartProps = {
  axes: RadarAxis[]; // 3-8, בסדר שהשרת קובע
  ariaLabel: string;
};
```

## מיפוי נתונים לממשק

כל אלמנט במסך מגיע משדה אחד בסכמה, בלי חישוב עסקי בצד הלקוח. הטבלה הזאת היא החוזה בין העיצוב ל-JSON.

| אלמנט במסך | שדות | כלל |
|---|---|---|
| לוגו, שם, טיקר | `company.logoUrl`, `name`, `ticker` | בלי לוגו: ריבוע שחור עם האות הראשונה. טיקר ושם באנגלית מוצגים LTR בתוך השורה |
| שורת משנה | `company.sector.name`, `report.fiscalYear` | ״טיקר · סקטור · דוח שנתי 2025״ |
| שורת סיכום | `summary.text` | עד 160 תווים, שורה אחת או שתיים |
| בורר שנים | `years` | ברירת מחדל: השנה האחרונה. נשמר ב-`?y=` |
| קודקוד ברדאר | `axes[i].scores[year].value` | רדיוס = ערך / 10 × R. זוית = −90° + 360° / N × i |
| ערך בקצה הצלע | `value` | שם הציר (12/500 מושתק) ומתחתיו הערך (16/700) |
| צורת החץ | `trend.direction` | `up` ▲, `down` ▼, `flat` –, `null` = אין חץ |
| צבע החץ | `trend.tone` | `positive` ירוק #15803d, `negative` אדום #b91c1c, `neutral` אפור #71717a |
| שורת ״למה כך?״ | `label`, `driver.label`, `value`, `trend` | סגורה. פתיחה קוראת ל-`detailUrl?year=` |
| ביטוי הסקטור בפירוט | `sectorMedian` ו-`sectorComparison.position` | ״מעל או מתחת לחציון הסקטור״, בלי צבע |
| אירועים | `events[]` | ממוינים מהחדש לישן, ברירת מחדל `importance >= 2`, עד 8, וקישור ״הצג הכל״ |
| איקון אירוע | `events[].type` | report FileText, acquisition GitMerge, leadership User, guidance TrendingUp/TrendingDown לפי `tone`, financing Banknote, legal Scale, regulatory Landmark, buyback Repeat, insider Users, other Circle (מ-lucide-react) |
| תאריך אירוע | `date`, `datePrecision` | `day` → 12.02.2026, `month` → 09.2025 |
| מספרים עיקריים | `keyMetrics[]` | הערך = האחרון ב-`series`. שינוי מ-`change`: צורה מ-`direction`, צבע מ-`tone` |

**גיאומטריית הרדאר**

- viewBox 390×330, מרכז (195, 170), R = 96 לערך 10, רדיוס תוויות 136.
- רשת: חמשה מצולעים בערכים 2, 4, 6, 8, 10, קו 1px ב-#e4e4e7.
- מצולע הנתונים: מילוי #18181b בשקיפות 12%, קו מתאר 2px, נקודות קודקוד ברדיוס 3.5.
- החישובים ב-`geometry.ts` בלבד (פונקציות טהורות, עם בדיקות יחידה), והרכיב רק מצייר את הפלט.
- עם יותר מ-6 צירים התוויות עלולות להתנגש, לכן השרת שולח `label` עד 16 תווים.

**פורמט מספרים**

- מטבע קומפקטי: `Intl.NumberFormat(locale, { style: 'currency', currency, notation: 'compact', maximumFractionDigits: 1 })` → $4.2B.
- אחוזים עם סימן: +12%, − 3% במינוס אמית (−), והכל באותה שורה עם direction: ltr.

## עיצוב: טוקנים, RTL ונגישות

העיצוב הוא shadcn Neutral על בסיס CSS variables, כך שמצב כהה ושפות נוספות לא ידרשו שינוי בקומפוננטות.

| טוקן | ערך | שימוש |
|---|---|---|
| `--background` | #ffffff | רקע העמוד (בלי כרטיסים) |
| `--foreground` | #09090b | טקסט ראשי |
| `--muted-foreground` | #71717a | טקסט משני (יחס ניגודיות 4.8:1 על לבן) |
| `--chart-ink` | #18181b | מצולע הרדאר ונקודותיו |
| `--chart-grid` | #e4e4e7 | רשת הרדאר |
| `--tone-positive` | #15803d | חץ ושינוי חיובי |
| `--tone-negative` | #b91c1c | חץ ושינוי שלילי |
| `--tone-neutral` | #71717a | חץ אפור, ערכים ללא שינוי |

**טיפוגרפיה ומרווחים**

- גופן Heebo (עברית ולטינית) 400/500/600/700. מספרים עם `font-variant-numeric: tabular-nums`.
- סקאלה: כותרת 20/700, בינוי סעיף 15/600, גוף 14, משני 13, הערה 12, מיקרו 11, ערך ברדאר 16/700.
- רוחב יחוס 390, מרווח דף 20, מרווח בין סעיפים 36, גובה שורה מינימלי 54. במסך רחב: עמוד במרכז עד 480.

**RTL**

- `<html lang="he" dir="rtl">` ומחלקות Tailwind לוגיות (`ms-*`, `pe-*`, `text-start`) במקום שמאל/ימין.
- טיקר, שם חברה, תאריכים ומספרים: `direction: ltr; unicode-bidi: isolate`.
- בורר השנים מוצג LTR (2023 → 2025) גם בדף RTL.
- החץ הפונה למטה בשורות אינו הופך לפי כיוון. הרדאר עצמו אינו תלוי כיוון.

**נגישות**

- צבע אינו אות יחיד: כל חץ בצורה (▲ ▼ –) בנוסף לצבע.
- יחס ניגודיות במינימום 4.5:1 לכל טקסט על רקע לבן, כולל הטונים הירוק והאדום.
- אזור לחיצה של לפחות 44×44 לכל שנה בבורר ולכל שורה. הבורר במאקאפים קטן מזה, ויש להגדיל את השטח הלחיץ.
- הרדאר הוא `role="img"` עם `aria-label` שמפרט את כל הצירים והערכים (״יציבות 7 מתוך 10…״). שורות הפירוט הן `button` עם `aria-expanded`.
- בורר השנים הוא shadcn Tabs, עם ניווט בחצים, ו-focus ring ברור.
- אנימציה היא רק הדהויה של עד 150ms בהחלפת שנה, ומבוטלת ב-`prefers-reduced-motion`.
- שורת ההבהרה (״למטרות מידע בלבד״) נמצאת בקבצי התרגום של הקליינט, לא בתשובת השרת.

## בדיקות ואבני דרך לבנייה

הקליינט נבנה בחמש אבני דרך, וכל אחת נגמרת במשהו שאפשר להריץ ולבדוק. אבן דרך 1–3 לא תלויות בשרת האמיתי.

| # | אבן דרך | תוצר | נגמר כש… |
|---|---|---|---|
| 1 | חוזה ו-mock | `/api/companies/{ticker}/report` נוסף ל-`openapi.json`, `npm run gen:api` רץ, ויש fixture אחד מלא ואחד עם `insufficient_data` | `npm run check:api` עובר ב-CI |
| 2 | גיאומטריית הרדאר | `geometry.ts` טהור ו-`RadarChart` מ-SVG, עם החלפת שנה וחצים | הרדאר זהה לעיצוב ב-390px, ו-3 עד 8 צירים מצוירים נכון |
| 3 | מסך חברה | כותרת, שורות "למה כך?", ציר זמן, מספרי מפתח ו-disclaimer | המסך נטען מה-fixture, כולל טעינה ושגיאה |
| 4 | חיבור לשרת | TanStack Query על ה-endpoint האמיתי, 202 או SSE, טעינה עצלה של פירוט ציר | חברה אחת מה-registry (למשל MLTM) נטענת מקצה לקצה במצב `cached` |
| 5 | חיזוק | נגישות, RTL, בדיקות e2e, מצבי קצה | סבב ידני בטלפון ו-Playwright ירוקים |

**בדיקות**

- **יחידה:** `geometry.ts` (זוויות, מיקום קודקוד לפי ציון, תוויות בקצה), פורמט מספרים ושנים, ומיפוי `tone` לצבע. הפונקציות טהורות, אז אין צורך ב-DOM.
- **רכיב:** `RadarChart` עם 3, 5 ו-8 צירים וציר עם ציון `null`; שורת "למה כך?" נפתחת וקוראת פירוט פעם אחת בלבד.
- **חוזה:** fixture-ים נבדקים מול ה-JSON Schema, ו-`check:api` נכשל אם `schema.d.ts` לא עדכני.
- **e2e:** הרחבת `e2e/ui-check.cjs` הקיים ב-Playwright: חיפוש, כניסה לחברה, החלפת שנה, פתיחת ציר ו-disclaimer גלוי.
- **נגישות:** אין ניגוד צבעים נמוך מ-4.5:1 בטקסט, והרדאר מקבל תיאור טקסטואלי מלא ל-screen reader.

הריפו עדיין בלי מסגרת בדיקות (יש רק `oxlint`), אז באבן דרך 1 מוסיפים Vitest ו-Testing Library.

## התאמה לריפו ושאלות פתוחות לצוות השרת

קראתי את `stock-analyzer` ("The Committee"). מה שהאיפיון הזה מניח לעומת מה שכבר קיים:

| נושא | בריפו היום | בהתאמה לאיפיון |
|---|---|---|
| מקור הנתונים | דוחות תקופתיים של חברות ישראליות, ב-FastAPI עם `openapi.json` כחוזה | endpoint חדש `GET /api/companies/{ticker}/report?mode=cached`, אותו prefix ואותו `mode` |
| ציונים 1–10 | אין. יש יחסים פיננסיים לפי שנה (`/ratios`) בקבוצות רווחיות, צמיחה, תשואה, נזילות, מינוף, תזרים, אשראי והלימות הון, ויש תווית יציבות מ-OSINT (`stable`, `watch`, `fragile`) | השרת צריך להמיר יחסים לציון לכל ציר, והמיפוי הזה ההחלטה הגדולה ביותר שפתוחה |
| ציר "ביטחון" | אין | מקביל ל-OSINT: `stable`, `watch`, `fragile` הופכים לציון גבוה/בינוני/נמוך, ו-`risks` הופך לפירוט הציר |
| ציר זמן אירועים | `findings` של OSINT עם `published_at`, `signal` ו-`source_url`, בחלון של 36 חודשים | `events` נבנה מהם: `signal` נהפך ל-`tone` |
| שגיאות | `{code, message}` | מחליף את problem+json שהצעתי, והקליינט כבר ממפה `code` ל-`ApiError` |
| עיבוד איטי | OSINT נשלח כ-SSE (`progress`, `done`, `error`) | להשתמש באותו מנגנון במקום 202 ו-polling; `web/src/api/sse.ts` קיים |
| שמות שדות | snake_case | הסכמה בדוגמה כתובה ב-camelCase; צריך להתאים ל-snake_case כדי שלא יהיה מיפוי ידני |
| ערכים כספיים | מחרוזות עשרוניות (`Decimal`), אחוזים כשברים | הקליינט מפרמט בלבד ולא מחשב |
| סטאק | React 19, Vite, Tailwind 4, shadcn, TanStack Query, Router, recharts, בלי Zod או i18next | לדלג על Zod (הטיפוסים מ-OpenAPI) ועל i18next (עברית בלבד); הרדאר נשאר SVG מותאם כי recharts לא נותן את החצים בקודקודים |

**שאלות לצוות השרת**

1. איך מחשבים ציון 1–10 מיחסים? ציון מוחלט, או מול חציון סקטור? אם מול סקטור, מאיפה החציון, כי בריפו יש כרגע שתי חברות (MLTM ועוד אחת).
2. האם אפשר לספק ציון לכל אחת משלוש השנים בתשובה אחת? `/ratios` כבר מחזיר שנים, אבל OSINT הוא תמונת מצב אחת, כך שציר "ביטחון" לא יהיה לו ערך היסטורי.
3. כמה צירים בפועל? ההסכמה הייתה על שלושה (יציבות, סיכון, צמיחה), והמוק מציג חמישה. תמחור דורש מחיר שוק, והריפו מבוסס על דוחות בלבד.
4. סיכון הפוך: האם השרת מחזיר "ביטחון" (גבוה = טוב) או שהקליינט הופך `11 − risk`? ההמלצה: השרת, כדי שכל ציר יהיה "גבוה = טוב".
5. 202 או SSE? ההמלצה: SSE, כמו ב-OSINT, כי כבר יש לו טיפול בשגיאות ובהתקדמות.
6. חברות בנקים וביטוח משתמשות בתבניות יחסים אחרות (`template`). האם מציגים אותן ברדאר זהה, או עם צירים אחרים?
7. לוגו: אין שדה לוגו ב-`CompanyOut`. מאיפה מגיע, ומה עושים כשחסר (ברירת מחדל: ראשי תיבות)?
8. חברה שלא נמצאת ב-`tracked_companies`: להחזיר 404 עם `code`, או להציע הוספה? `POST /api/companies` עובד רק במצב live.
9. טקסט "למה כך?": נוצר מראש על ידי LLM ונשמר, או נוצר בבקשה? בריפו יש `LLM_FAKE` ו-`ALLOW_LIVE`, ובמצב cached אסור לקרוא ללוגיקה שעולה כסף.
10. הרשאות ו-CORS: האם יש אימות, או שה-API פתוח כמו היום? המוצר פונה לסוחרים, אז צריך להחליט לפני שחושפים החוצה.

**מה בלי תשובה אפשר להתחיל**

אבני דרך 1–3 לא תלויות באף אחת מהשאלות האלה, כי עובדים מול fixture. התשובות לשאלות 1, 3 ו-4 משנות רק את תוכן ה-fixture ולא את הקוד.

## פרומפט ל-Claude Code

כן, המימוש יורץ דרך פרומפט, והוא בנוי לריצה בשלבים. הפרומפט הזה מכסה רק אבן דרך 1 ו-2, ועוצר לבדיקה לפני ההמשך. לפני הריצה: ייצו את המסמך כ-Markdown ושימו אותו בריפו ב-`docs/company-report-spec.md`, כי Claude Code לא יכול לקרוא קישור מ-claude.ai.

```markdown
You are building the "company report" screen of the web client in `web/`.
The full spec is `docs/company-report-spec.md`. Read it end to end first, then read
`web/README.md`, `web/src/api/client.ts`, `web/src/api/sse.ts` and the existing
feature folders under `web/src/features/` to learn the conventions.

Scope: milestones 1 and 2 of the spec only. Stop after milestone 2 and summarize.

## Milestone 1: contract and fixtures
- Add the `CompanyReport` types. The server endpoint
  `GET /api/companies/{ticker}/report` does not exist yet, so put the types in
  `web/src/features/report/types.ts`, copied from the JSON Schema in the spec, with a
  TODO to replace them with the generated `schema.d.ts` types once the server ships it.
- Field names are snake_case, exactly as in the spec. Money values are decimal strings.
- Create two fixtures in `web/src/features/report/fixtures/`: `mltm.full.json` (the
  example from the spec, with 5 axes) and `mltm.sparse.json` (3 axes, one axis with
  `status: "insufficient_data"` and `null` scores).
- Add a `useReport(ticker)` hook on TanStack Query. For now it returns the fixture
  after a short delay; keep the real call behind one function so it swaps in one place.

## Milestone 2: the radar
- `web/src/features/report/radar/geometry.ts`: pure functions, no React. viewBox
  390x330, center (195,170), radius 96, label radius 136, grid rings at 2/4/6/8/10,
  3 to 8 axes, first axis at the top, clockwise.
- `RadarChart.tsx`: custom SVG, not recharts. Neutral shadcn look: black polygon
  (#18181b at 12% fill), grid #e4e4e7, no card, border, legend or colored dots.
  A value and an arrow at every vertex. Arrow color comes from `trend.tone`
  (positive #15803d, negative #b91c1c, neutral #71717a); never compute it from the numbers.
- A year switcher (2023 | 2024 | 2025) that swaps the scores on the client, no refetch.
- An axis with `status: "insufficient_data"` shows a dash and no arrow.
- Page and labels are RTL (`dir="rtl"`). Labels in Hebrew from the fixture.
- Accessibility: `role="img"` plus a text description listing every axis and score.
- Add Vitest and Testing Library to `web/` (none exist yet). Unit-test `geometry.ts`
  (angles, vertex positions, 3/5/8 axes) and the tone-to-color mapping, and render-test
  `RadarChart` with both fixtures.
- Add a temporary route `/dev/radar` that shows both fixtures.

## Rules
- Do not touch `server/`. Do not add Zod or i18next. Hebrew strings are plain constants.
- Use the existing shadcn components and Tailwind tokens. No new UI libraries.
- `npm run lint`, `npm run build` and the new tests must pass before you stop.
- Commit in small steps, one per milestone.
```

באבן הדרך הבאה (מסך החברה והחיפוש) אפשר להריץ פרומפט דומה, אחרי שבדקתם את הרדאר.
