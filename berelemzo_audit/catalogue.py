"""A 24 kontroll katalógusa. A kontrollcél és az auditpróba szó szerint a bértranszparencia-auditkézikönyv
kontrollkatalógusából (3. szakasz) származik; a `mode` a motor módosítása: mit tud a motor ténylegesen számolni.

mode:
  COMPUTED  – az egyéni szintű adatból vagy az eredményből számolható
  MIXED     – részben számolható, részben nyilatkozat kell
  DECLARED  – a motor csak a nyilatkozat meglétét és belső egyezését tudja vizsgálni
"""

from __future__ import annotations

SOURCE = "auditkézikönyv, 3. Kontrollkatalógus"

CONTROLS = [
    # id, csoport, kontrollcél, auditpróba, mode
    ("GOV-01", "Irányítás", "Jóváhagyott bértranszparencia-felelős és döntési RACI.", "Éves kontroll; vezetői jóváhagyás.", "DECLARED"),
    ("GOV-02", "Irányítás", "Független jogi és munkavállalói képviseleti kontroll.", "Érintettség és jegyzőkönyv.", "DECLARED"),
    ("JOB-01", "Munkakör", "Minden aktív munkakörnek verziózott, tényleges munkakörprofilja van.", "100%-os katalógus-egyezés.", "COMPUTED"),
    ("JOB-02", "Munkakör", "A négy főfaktor és minden releváns követelmény lefedett.", "Hiány- és nődomináns munkakör teszt.", "COMPUTED"),
    ("JOB-03", "Munkakör", "Pontozás kettős vagy kalibrált, indoklással.", "Minta újrapontozása.", "MIXED"),
    ("JOB-04", "Munkakör", "FEOR/ESCO csak referencia, nem automatikus érték.", "Rendszerszabály és interjú.", "DECLARED"),
    ("PAY-01", "Díjazás", "A teljes díjazás minden eleme integrált.", "Bérszámfejtés–főkönyv egyeztetés.", "MIXED"),
    ("PAY-02", "Díjazás", "FTE, időszak, valuta és távollét normalizálása dokumentált.", "Újraszámítás és edge case.", "MIXED"),
    ("PAY-03", "Díjazás", "Bérsáv és fejlődési kritérium hozzáférhető.", "Szabályzat és munkavállalói próbakérelem.", "MIXED"),
    ("OBJ-01", "Objektív indok", "Minden sávon kívüli vagy peer-eltéréshez objektív indokrekord.", "Célzott mintavétel.", "COMPUTED"),
    ("OBJ-02", "Objektív indok", "A piaci, megtartási és teljesítményoknak lejárata van.", "Lejárt indokok listája.", "COMPUTED"),
    ("OBJ-03", "Objektív indok", "A teljesítményértékelés nemsemleges és kalibrált.", "Pontszámeloszlás és vezetői variancia.", "MIXED"),
    ("STA-01", "Statisztika", "Átlag, medián, változó bér és kvartilis számítás reprodukálható.", "Független újraszámítás.", "COMPUTED"),
    ("STA-02", "Statisztika", "Kategórián belüli 5%-os trigger és 6 hónapos korrekció figyelt.", "Szimuláció és eseménynapló.", "MIXED"),
    ("STA-03", "Statisztika", "Kis mintáknál bizonytalanság és adatvédelmi korlát jelölt.", "Outputreview.", "COMPUTED"),
    ("TRN-01", "Átláthatóság", "Felvételi bérsáv-közlés és bértörténeti kérdés tilalma.", "Hirdetés- és interjúminta.", "MIXED"),
    ("TRN-02", "Átláthatóság", "Két hónapon belüli információkérési folyamat.", "Asztali gyakorlat.", "MIXED"),
    ("TRN-03", "Átláthatóság", "Éves munkavállalói tájékoztatás és hozzáférhető bérkritérium.", "Közlési bizonyíték.", "DECLARED"),
    ("REP-01", "Jelentés", "Jelentési naptár létszámküszöb szerint.", "Határidő- és felelősmátrix.", "MIXED"),
    ("REP-02", "Jelentés", "Közös bérértékelés eljárása és korrekciós terv sablon.", "Triggergyakorlat.", "MIXED"),
    ("DPR-01", "Adatvédelem", "Hozzáférési mátrix, célhoz kötöttség, megőrzés.", "Jogosultságminta.", "MIXED"),
    ("DPR-02", "Adatvédelem", "Kis csoportok védelme nem üresíti ki a munkavállalói jogot.", "Adatvédelmi és jogi ellenőrzés.", "MIXED"),
    ("CHG-01", "Változáskezelés", "Munkakör-változáskor újraértékelési trigger.", "Változásminta.", "MIXED"),
    ("CHG-02", "Változáskezelés", "Jogszabály- és módszertanfigyelés tulajdonossal.", "Frissítési napló.", "DECLARED"),
]

BY_ID = {c[0]: c for c in CONTROLS}

# Jelentési ütemezés a tudásbázisból (01-jogi-es-szabalyozasi-elemzes, 117–121. sor). Állapot: REVIEW_REQUIRED,
# az EUR-Lex szövegével és a magyar átültetéssel a jogi képviselet egyezteti. A magyar átültetés állapota nem ellenőrzött.
REPORTING_SCHEDULE = [
    {"min_headcount": 250, "max_headcount": None, "first_report": "2027-06-07", "then": "évente"},
    {"min_headcount": 150, "max_headcount": 249, "first_report": "2027-06-07", "then": "háromévente"},
    {"min_headcount": 100, "max_headcount": 149, "first_report": "2031-06-07", "then": "háromévente"},
]
REPORTING_SOURCE = "tudásbázis 01, 5. szakasz; REVIEW_REQUIRED; a magyar átültetés állapota nem ellenőrzött"

# A tudásbázis szerint lejárattal kell rendelkezniük (OBJ-02): piaci, megtartási és teljesítményindok.
EXPIRY_REQUIRED_TYPES = {"teljesítmény", "teljesitmeny", "hiányszakma", "hianyszakma", "piaci", "megtartás", "megtartas"}

TRIGGER_GAP = 0.05          # kategórián belüli 5%-os trigger (STA-02)
CORRECTION_MONTHS = 6       # 6 hónapos korrekciós figyelés (STA-02)
INFO_REQUEST_MONTHS = 2     # két hónapon belüli válasz (TRN-02)
ANNUAL_DAYS = 366           # „éves” kontrollok (GOV-01, TRN-03, CHG-02)
MIN_CELL_FLOOR = 5          # a domain cellaminimuma
