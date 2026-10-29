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

## Licenc

Minden jog fenntartva, lásd a [`LICENSE`](LICENSE) fájlt.
