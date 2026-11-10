import pytest

from stock_analyzer.ingest.normalize import normalize, normalize_title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ש״ח", 'ש"ח'),
        ('ש"ח', 'ש"ח'),
        ("מנכ״ל", 'מנכ"ל'),
        ("ר׳ סעיף", "ר' סעיף"),
        ("“quoted” ‘single’", "\"quoted\" 'single'"),
        ("‏שלום‎ ‫עולם‬", "שלום עולם"),
        ('**מלם תים בע"מ**', 'מלם תים בע"מ'),
        ("**<u>ביאור 1 - כללי</u>**", "ביאור 1 - כללי"),
        ("תחומי הפעילות<br>של הקבוצה", "תחומי הפעילות של הקבוצה"),
        ("א<br/>ב<BR />ג", "א ב ג"),
        ("P&amp;S ו-&quot;החברה&quot;", 'P&S ו-"החברה"'),
        ("Error or Omissions &amp;amp; Products", "Error or Omissions & Products"),
        ("  רווח   \t גולמי \n\n שנתי  ", "רווח גולמי שנתי"),
        ("טקסט<!-- page 5 -->המשך", "טקסט המשך"),
        ("34.8%   (AI)", "34.8% (AI)"),
        ("", ""),
    ],
)
def test_normalize_table(raw, expected):
    assert normalize(raw) == expected


def test_gershayim_variants_are_equal():
    assert normalize("הכנסות של 1,635 מיליון ש״ח") == normalize('הכנסות של 1,635 מיליון ש"ח')
    assert normalize("בע״מ") == normalize("בע”מ") == normalize('בע"מ')


def test_keep_newlines():
    assert normalize("**שורה**  אחת\n\n  שורה   שתיים ", keep_newlines=True) == "שורה אחת\n\nשורה שתיים"


def test_idempotent():
    s = "**<u>תלות  בתקציבי</u>** המדינה ש״ח &amp;‏"
    assert normalize(normalize(s)) == normalize(s)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("## 22.2 גורמי סיכון ענפיים", "22.2 גורמי סיכון ענפיים"),
        ("- **ביאור 5 - מזומנים**", "ביאור 5 - מזומנים"),
        ("**.22 דיון בגורמי סיכון.**", "22 דיון בגורמי סיכון"),
    ],
)
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected
