# Bérelemző (`berelemzo`)

> Állapot: korai, még nem futtatták valós szervezeten. A szerzői adatok a bírálat után kerülnek feltüntetésre.

Önálló, futtatható modul a nemek közötti bérrés kategóriánkénti kiszámítására. **Determinisztikus, szabályalapú és statisztikai számítás: nincs benne gépi tanulás, nyelvi modell, hálózati hívás vagy naplózás.** Ugyanarra a bemenetre mindig ugyanazt az eredményt adja, és az eredményhez lenyomat tartozik.

A modul csak a számítást tartalmazza. Jogi tudásanyagot, jogi tanácsot és jogsértés-minősítést nem ad.

## Futtatás

```bash
python -m berelemzo --config konfig.json --data berek.csv --out eredmeny.json
```

Csak a szabványos Python könyvtárat használja (Python 3.11+). A tesztek:

```bash
python -m unittest discover -s berelemzo -t . -v
```

## Bemenet

**Konfiguráció (JSON)** – emberi döntések, személyes adat nélkül. Példa: [`examples/config.example.json`](berelemzo/examples/config.example.json).

- `scheme.weights`: a (rész)faktorok súlyai (összegük 1). `scheme.level_max`: a szintskála felső vége, egy szám (alapértelmezés 5) vagy részfaktoronkénti lista. Az EIGE-eszköztárban a szaktudás részfaktor skálája 0–8, a többié 0–5, ezért az EIGE 14 részfaktoros sémához lista kell: [`berelemzo/examples/config.eige14.example.json`](berelemzo/examples/config.eige14.example.json).
- `jobs`: munkakör → szintek listája, a súlyokkal azonos hosszban. Minden szint 0 és a saját részfaktorának skálamaximuma között legyen.
- `band_width`: a pontsáv szélessége (alapértelmezés 5 pont), `min_cell`: nemenkénti minimum létszám kategóriánként (alapértelmezés és alsó korlát: 5, nem csökkenthető).

**Bérfájl (CSV)** – pontosan három oszlop: `job_id`, `sex`, `pay`. Egyéni azonosító nincs. A tizedesjel pont, nem lehet ezres elválasztó. Másik elválasztó: `--delimiter ";"`.

## Módszer

| Lépés | Számítás |
|---|---|
| S1 | munkakör-pontszám: `S_j = 100 · Σ w_k · ℓ_jk / ℓ_max,k` (a skálamaximum részfaktoronként eltérhet) |
| S2 | kategória: `g_j = ceil(S_j / band_width)` |
| S3 | nemenkénti összevonás kategóriánként |
| S4 | hézag: `G_c = (átlag_férfi − átlag_nő) / átlag_férfi`, számtani bérátlagból |
| S5 | `T_c = [G_c ≥ 0,05]`; mintavételi jelzés = `T_c` és Welch-féle egyoldali t-próba (5%, a bérek logaritmusán, Welch–Satterthwaite szabadságfokkal) |

A kategóriánként közölt `p_point_trigger_if_no_gap` azt adja meg, mekkora eséllyel érné el a pontbecslés az 5%-ot valós hézag nélkül (`1 − Φ(−ln 0,95 / SE)`). A szervezetszintű összegzés ebből adja a várható küszöbérintések számát és a legalább egy érintés valószínűségét (többszörös összehasonlítás; a kategóriák függetlenségét feltételezi).

**Feltevés:** a szint→pont átváltás lineáris (a szint osztva a részfaktor skálamaximumával). Az EIGE-eszköztár Excel-munkafüzetének tényleges képletét nem vizsgáltuk, ezért ezt az egyezést a használat előtt ellenőrizni kell.

**Amit a modul nem csinál:** nem állapít meg jogsértést, nem hoz létre közös bérértékelési kötelezettséget (`O_c`), nem dönt az indoklásról (`J_c`) és az orvoslásról (`R_c`). Ezek emberi döntések. A mediánhézagot sem számolja, mert ahhoz egyedi sorokra volna szükség.

## Adatvédelem (GDPR) – a kódban érvényesített szabályok

| Szabály | Hol érvényesül |
|---|---|
| Adatminimalizálás: csak `job_id`, `sex`, `pay` | `intake.py`, fehérlista; minden más oszlop (név, adószám, bankszámlaszám, e-mail) elutasítva |
| Nincs egyéni azonosító, sor nem marad meg | beolvasáskor azonnal munkakörönkénti összegzés (Welford/Chan) |
| Kis cellák elnyomása | `n_nő < min_cell` vagy `n_férfi < min_cell` esetén a kategória csak elnyomás-jelzést kap, számot nem |
| Kis kizárt darabszám nem közölhető | az `excluded` értékei `<5` alakban jelennek meg, ha 1–4 között vannak |
| Hibaüzenet nem szivárogtat | csak sor- és mezőnév szerepel, cellaérték soha |
| Nincs hálózat, MI, naplózás, külső csomag | `tests/test_boundary.py` az importokat ellenőrzi |
| A bemeneti fájl nem íródik felül | a CLI megtagadja, ha a kimenet azonos a bérfájllal vagy már létezik |
| Szintetikus teszt-adat | a repóba valós vagy valósághű bérsor nem kerül; a tesztek futásidőben generálnak |

Az eredményfájl csak kategóriaszintű aggregátumot tartalmaz, mégis emberi felülvizsgálat kell, mielőtt a szervezeten kívülre kerül.

**Határ:** ez a lista a modul működésének adatvédelmi tulajdonságait írja le, nem tanúsítja egy szervezet GDPR-megfelelőségét. A jogalap, a megőrzési idő, az érintetti tájékoztatás és az adatvédelmi hatásvizsgálat az adatkezelő feladata.

**Maradék kockázat:** az aggregátumból is következtetni lehet egyénre, ha kis csoportok vagy egymást kiegészítő kategóriák kerülnek közlésre. Az 5-ös cellaküszöb és a darabszámok elnyomása ezt csökkenti, de nem szünteti meg; a közzététel előtt emberi felülvizsgálat kell.

## Verzió és lenyomat

Az eredmény tartalmazza a `method_id`, a `core_version`, a konfiguráció SHA-256 lenyomatát és a teljes eredmény lenyomatát (`fingerprint.result`). A lebegőpontos kimenetek kerekítve szerepelnek, hogy a lenyomat gépek között is stabil legyen.

## Állapot

Jelölés: `COMPUTED_MEASURED` a szintetikus tesztvilágra; valós szervezeten még nem futtatta senki. Jogi minősítés: `REVIEW_REQUIRED`.

## Eredmény-ellenőrző (L1): `berelemzo_verify`

Független, determinisztikus, MI-mentes ellenőrző a Bérelemző eredményfájljához. **Nem importálja a `berelemzo` csomagot**, és saját t-eloszlást használ, hogy a mag hibája ne másolódjon át az ellenőrzésbe. Csak a szabványos könyvtárat használja.

```bash
python -m berelemzo_verify --result eredmeny.json --config konfig.json --out l1.json
```

Kilépési kód: 0 (nincs FAIL), 1 (van FAIL), 2 (bemeneti hiba). A konfiguráció nélkül a V03 kihagyásra kerül.

| ID | Ellenőrzés |
|---|---|
| V01 | séma és kulcs-fehérlista |
| V02 | az eredmény SHA-256 lenyomatának újraszámolása |
| V03 | a konfiguráció lenyomata és a paraméterek egyezése |
| V04 | ismert módszer, verzió és státuszjelölések |
| V05 | elnyomási invariáns (az elnyomott kategória nem tartalmaz számadatot) |
| V06 | cellaminimum (közölt kategóriában nemenként legalább `min_cell` ≥ 5) |
| V07 | küszöbérintés konzisztenciája (gap ≥ küszöb) |
| V08 | Welch-jelzés konzisztenciája (t > kritikus érték) |
| V09 | a kritikus t-érték független újraszámítása |
| V10 | a mintavételi jelzés (küszöbérintés ∧ Welch) konzisztenciája |
| V11 | az összegzés újraszámítása |
| V12 | a kategóriánkénti és a szervezetszintű valószínűségek újraszámítása |
| V13 | sávszerkezet |
| V14 | konfiguráció-épség (súlyok, skálák, küszöbök) |
| V15 | előjel-plauzibilitás (heurisztika, WARN) |
| V16 | kizárt darabszámok védelme (kis szám csak „<k” alakban) |
| V17 | számok épsége (nincs NaN, végtelen, ésszerűtlen érték) |
| V18 | szabad szöveges mezők biztonsága (azonosító-, URL- és utasításszerű minták) |

Minden megállapítás JSON-mutató lelőhelyet kap. A rekord kimondja a lefedettség korlátait: **a „nincs eltérés” nem azonos azzal, hogy „helyes”.** Az L1 nem vizsgálja a nyers adatot, a módszertan helyességét és a jogi megfelelést.

### Az ellenőrző saját ellenőrzése

A `berelemzo_verify.mutations` ismert jó eredmény 23 szándékosan elrontott változatát tartalmazza (hibás lenyomat, megszegett elnyomás, megfordított küszöb, hamis szabadságfok, beágyazott utasítás stb.). A benchmark az észlelési arányt és a téves riasztást méri:

```bash
python -m berelemzo_verify.benchmark --result tiszta_eredmeny.json --config konfig.json
```

Minden V01–V18 ellenőrzéshez van legalább egy mutáció, és a tesztek ezt kikényszerítik. A tiszta eredményen nem keletkezhet FAIL vagy WARN.

## Megfelelőségi audit-motor: `berelemzo_audit`

Determinisztikus, MI-mentes motor, amely a beérkezett adatokon a bértranszparencia-auditkézikönyv **24 kontrollját** (GOV, JOB, PAY, OBJ, STA, TRN, REP, DPR, CHG) értékeli. A kontrollcélok és az auditpróbák szó szerint a kézikönyv katalógusából származnak. A motor a két meglévő rekordellenőrzőt (munkakörértékelés és aggregált bérrés-elemzés) is tartalmazza, és az aggregált mutatókból ilyen rekordokat épít.

```bash
python -m berelemzo_audit --data adat.csv --config konfig.json --audit-date 2026-10-29     --declarations nyilatkozat.json --result eredmeny.json --input-reality REAL --out audit.json
```

Az adatfájlt **helyben** kell futtatni. A kimenet csak aggregátum; ha a kimeneti kapu `BLOCKED`, a fájl nem íródik ki (kilépési kód 3). Kilépési kódok: 0 (nincs NOT_MET), 1 (van NOT_MET), 2 (bemeneti hiba), 3 (kapu blokkolt).

### Bemenetek

| Bemenet | Tartalom |
|---|---|
| `--data` | CSV, fehérlistás oszlopok: `job_id`, `sex`, `fte`, `alapber`, `rendszeres_potlek`, `valtozo_bonusz`, `termeszetbeni`, `tulora`, `kifizetett_osszes_kezi`, `szerzodes_tipus`, `belepes_eve`, `munkahely`, `muszakrend`, `iskolai_vegzettseg`, `teljesitmenysav`, `eletkor_sav`. A fehérlistán kívüli oszlop **értékét a beolvasó nem olvassa ki**, csak a nevét jelzi (DPR-01). Az `fte` kötelező, a normalizálás pontosan egyszer, a motorban történik. |
| `--config` | A Bérelemző konfigurációja (súlyok, szintek, sávszélesség). Pontozás nélkül `{"grouping": "job", "min_cell": 5}`: minden munkakör külön csoport (azonos munka). Ekkor a JOB-01–03 kontroll `NOT_ASSESSABLE`, és a kategóriák nem egyenlő értékű munkát jelentenek. |
| `--declarations` | A szervezet nyilatkozatai (JSON, minden kulcs opcionális): `organisation`, `governance`, `job_catalogue`, `job_evaluation`, `pay_elements`, `reconciliation`, `normalization`, `pay_bands`, `pay_policy`, `scoring_log`, `justifications`, `deviation_register`, `info_requests`, `transparency`, `reporting`, `joint_assessment`, `data_protection`, `change_management`. A `justifications[].row` az adatsor sorszáma a fájlban (a fejléc után, 1-től). |
| `--pay-basis` | `components` (alapértelmezés): a komponensek a kifizetett összegek, a fájl összege ezek összege. `total`: az összes díjazás oszlop a kifizetett összeg, a komponensek teljes munkaidős összegek. Ha az összes díjazás a részmunkaidősöknél pontosan komponensösszeg × fte, a motor jelzi (PAY-01, PAY-02), mert a normalizálás kétszeres lehet; ilyenkor mindkét alappal érdemes futtatni. |
| `--result` | A Bérelemző eredményfájlja: a motor kereszt-ellenőrzi egy független újraszámítással, és lefuttatja rajta az L1 ellenőrzőt. |

### Státuszok és bizonyítékszint

| Státusz | Jelentés | Bizonyíték |
|---|---|---|
| `MET` | az adatból vagy az eredményből számolva teljesül | `COMPUTED_MEASURED` |
| `NOT_MET` | számolva vagy a nyilatkozat tartalma szerint nem teljesül | |
| `DECLARED_ONLY` | formailag teljesül, de csak nyilatkozat alapján; a motor nem tudja igazolni | `DECLARED` |
| `NOT_ASSESSABLE` | a bemenet hiányzik; a `needs` felsorolja, mi kell | `UNVERIFIABLE` |
| `MANUAL_REVIEW` | emberi mérlegelés kell; a számolt szűrés csatolva | |

A motor **nem engedi**, hogy egy kontroll a bizonyítékszintjénél erősebb státuszt kapjon (`CeilingError`). A státusz a katalógus kontrollcéljához képesti állapot, **nem jogi minősítés**.

### Mit számol a motor kontrollonként

| Kontroll | Számolt rész | Nyilatkozatból |
|---|---|---|
| GOV-01, GOV-02 | | felelős, RACI, jóváhagyás kora; jogi és képviseleti felülvizsgálat |
| JOB-01 | az adat munkakörei és a pontozott munkakörök egyezése | profilok verziója és hivatkozása |
| JOB-02 | főfaktor-lefedettség, 0 szintek indoklása, nő- és férfidomináns munkakörök szintátlagai | indoklások |
| JOB-03 | kettős pontozás aránya, értékelői egyezés, konszenzus az értékelői tartományban, 10%-os újrapontozási minta | a pontozási napló |
| JOB-04 | | FEOR/ESCO csak referencia |
| PAY-01 | deklarált elemek az adatban, létszám- és összegegyeztetés a deklarált bérszámfejtéssel | a bérszámfejtési összegek |
| PAY-02 | érvényes FTE, normalizált összeg újraszámítása, kétszeres normalizálás mintázata | dokumentáció |
| PAY-03 | bérsávtábla belső épsége | a kritérium hozzáférhetősége |
| OBJ-01 | sávon kívüli (és ha megadott, peer-eltérő) díjazás, indokrekord-lefedettség | indokrekordok |
| OBJ-02 | | lejárat nélküli vagy lejárt indokok a nyilatkozott rekordokban |
| OBJ-03 | nemek szerinti értékelés-eloszlás, Mann–Whitney szűrés (nem igazolja a semlegességet) | kalibráció |
| STA-01 | átlag, medián, változó díjazás két független úton; kereszt-ellenőrzés a Bérelemző eredményével | |
| STA-02 | kategóriánkénti 5%-os küszöbérintés, a Welch-jelzés, a korrekciós ablak | indok és korrekciós terv (`deviation_register`) |
| STA-03 | elnyomás, bizonytalansági mutató, az eredmény L1 állapota | |
| TRN-01 | hirdetések bérsáv-aránya | a bértörténeti kérdés tilalma |
| TRN-02 | a két hónapos válaszhatáridő a naplóból | az információkérési napló |
| TRN-03, CHG-02 | frissesség | a közlés és a frissítési napló |
| REP-01 | létszám szerinti jelentési sáv és határidő | naptár és felelős |
| REP-02 | közös bérértékelést indokló kategóriák száma | eljárás és sablon |
| DPR-01 | nem engedélyezett oszlopok a fejlécben | hozzáférési mátrix, cél, megőrzés |
| DPR-02 | az elnyomott kategóriákban lévő munkavállalók aránya | kiegészítő megoldás |
| CHG-01 | | munkakör-változás és újraértékelés naplója |

Az aggregált mutatók: átlagos és medián bérkülönbség, a változó díjazás különbsége és aránya, a nők és férfiak száma a négy bérkvartilisben, kategóriánkénti átlag- és mediánrés. A nemenként 5 fő alatti cellák elnyomottak, az 1–4 közötti darabszámok „<5” alakban szerepelnek.

### Feltevések és korlátok

- A kvartilis-határ az `inclusive` módszerű kvantilis, a nő- és férfidomináns munkakör küszöbe 0,7, a pontsáv a Bérelemző szabálya. A kézikönyv ezeket nem rögzíti, ezért **feltevések**.
- A jelentési ütemezés (REP-01) a tudásbázisból származik, `REVIEW_REQUIRED`; a magyar átültetés állapota nem ellenőrzött.
- A `DECLARED_ONLY` kontrollokat a motor **nem tudja igazolni**. A küszöbérintés nem azonos a közös bérértékelési kötelezettséggel; az indoklás és az orvoslás emberi, jogi döntés.
- A motort szintetikus adaton ellenőriztük; valós szervezeten még nem futott.
- Ha egyetlen kategória sem éri el a cellaminimumot, a STA-02 `NOT_ASSESSABLE` (nem `MET`): üres halmazra nem állítható teljesülés. A változó díjazás mutatói elnyomottak, ha valamelyik nem 1–4 fős kedvezményezett-csoportot jelent.
- Az `ABOVE_THRESHOLD_REVIEW` bérrés-rekord csak bizonyítékhivatkozással érvényes; hivatkozás nélkül a `pay_equity_records_not_valid` listába kerül, hibaüzenettel.

## Licenc

Minden jog fenntartva, lásd a [`LICENSE`](LICENSE) fájlt.
