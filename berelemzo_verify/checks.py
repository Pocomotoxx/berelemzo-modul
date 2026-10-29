"""A V01–V18 ellenőrzések. Tiszta függvények: nincs fájl-, hálózat- vagy naplózási művelet.

Minden ellenőrzés egy rekordot ad: {id, name, status, detail, findings}. A status:
PASS (nincs eltérés ebben az ellenőrzésben), FAIL (eltérés), WARN (heurisztikus jelzés), SKIPPED (nem futtatható).
A `findings` JSON-mutató (RFC 6901) lelőhelyeket tartalmaz, hogy a hivatkozás kóddal feloldható legyen.
"""

from __future__ import annotations

import math
import re

from .canon import canonical_config, sha256
from .tdist import upper_quantile

KNOWN_METHODS = {"berelemzo/1"}
TOP_KEYS = {"method_id", "core_version", "evidence_level", "legal_status", "parameters", "categories",
            "summary", "excluded", "notes", "fingerprint"}
PARAM_KEYS = {"weights", "level_max", "band_width", "min_cell", "trigger_gap", "alpha", "config_sha256"}
SUMMARY_KEYS = {"categories_total", "categories_reported", "categories_suppressed", "point_threshold_hits",
                "sampling_signals", "expected_point_hits_if_no_gap", "p_any_point_hit_if_no_gap"}
CAT_SUPPRESSED = {"grade", "score_range", "suppressed"}
CAT_REPORTED = CAT_SUPPRESSED | {"n_f", "n_m", "gap", "se_log", "t", "df", "t_crit", "t_c_point_threshold",
                                 "welch_significant", "sampling_signal", "p_point_trigger_if_no_gap"}
FP_KEYS = {"algorithm", "result"}
MAX_FINDINGS = 25

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_LONG_DIGITS = re.compile(r"(?<!\d)\d{9,}(?!\d)")
_INSTRUCTION = re.compile(
    r"ignore (all |any |the )?(previous|prior|above)|disregard|system prompt|you are now|act as |"
    r"hagyd figyelmen kívül|felejtsd|új utasítás|utasítás:|<\|", re.IGNORECASE)


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _fin(x) -> bool:
    return _num(x) and math.isfinite(x)


def ptr(*parts) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _rec(cid: str, name: str, findings: list, detail_ok: str = "", *, warn: bool = False) -> dict:
    if not findings:
        return {"id": cid, "name": name, "status": "PASS", "detail": detail_ok, "findings": []}
    return {"id": cid, "name": name, "status": "WARN" if warn else "FAIL",
            "detail": f"{len(findings)} eltérés", "findings": findings[:MAX_FINDINGS]}


def _skip(cid: str, name: str, why: str) -> dict:
    return {"id": cid, "name": name, "status": "SKIPPED", "detail": why, "findings": []}


def _f(locator: str, detail: str) -> dict:
    return {"locator": locator, "detail": detail}


# ---------------------------------------------------------------- V01
def v01_schema(r: dict) -> dict:
    out = []
    if not isinstance(r, dict):
        return _rec("V01", "Séma és kulcs-fehérlista", [_f("", "a gyökér nem objektum")])
    missing, extra = TOP_KEYS - set(r), set(r) - TOP_KEYS
    for k in sorted(missing):
        out.append(_f(ptr(k), "hiányzó kulcs"))
    for k in sorted(extra):
        out.append(_f(ptr(k), "ismeretlen kulcs"))
    if out:
        return _rec("V01", "Séma és kulcs-fehérlista", out)
    p = r["parameters"]
    if not isinstance(p, dict) or set(p) != PARAM_KEYS:
        out.append(_f(ptr("parameters"), "a paraméterek kulcskészlete hibás"))
    s = r["summary"]
    if not isinstance(s, dict) or set(s) != SUMMARY_KEYS:
        out.append(_f(ptr("summary"), "az összegzés kulcskészlete hibás"))
    fp = r["fingerprint"]
    if not isinstance(fp, dict) or set(fp) != FP_KEYS:
        out.append(_f(ptr("fingerprint"), "a lenyomat kulcskészlete hibás"))
    for k in ("method_id", "core_version", "evidence_level", "legal_status"):
        if not isinstance(r[k], str):
            out.append(_f(ptr(k), "szöveg kell"))
    if not isinstance(r["notes"], list) or not all(isinstance(x, str) for x in r["notes"]):
        out.append(_f(ptr("notes"), "szövegek listája kell"))
    ex = r["excluded"]
    if not isinstance(ex, dict) or not all(isinstance(k, str) and (_int(v) or isinstance(v, str)) for k, v in ex.items()):
        out.append(_f(ptr("excluded"), "szöveg → egész vagy szöveg leképezés kell"))
    cats = r["categories"]
    if not isinstance(cats, list):
        out.append(_f(ptr("categories"), "lista kell"))
        return _rec("V01", "Séma és kulcs-fehérlista", out)
    for i, c in enumerate(cats):
        if not isinstance(c, dict) or not isinstance(c.get("suppressed"), bool):
            out.append(_f(ptr("categories", i), "a kategória hibás szerkezetű"))
            continue
        want = CAT_SUPPRESSED if c["suppressed"] else CAT_REPORTED
        for k in sorted(want - set(c)):
            out.append(_f(ptr("categories", i, k), "hiányzó kulcs"))
        if not c["suppressed"]:  # az elnyomott kategória többletkulcsait a V05 jelzi, külön és megnevezve
            for k in sorted(set(c) - want):
                out.append(_f(ptr("categories", i, k), "ismeretlen kulcs"))
        if not _int(c.get("grade")):
            out.append(_f(ptr("categories", i, "grade"), "egész kell"))
        sr = c.get("score_range")
        if not (isinstance(sr, list) and len(sr) == 2 and all(_num(x) for x in sr)):
            out.append(_f(ptr("categories", i, "score_range"), "két számból álló lista kell"))
        if not c["suppressed"]:
            for k in ("n_f", "n_m"):
                if k in c and not _int(c[k]):
                    out.append(_f(ptr("categories", i, k), "egész kell"))
            for k in ("gap", "se_log", "p_point_trigger_if_no_gap"):
                if k in c and not _num(c[k]):
                    out.append(_f(ptr("categories", i, k), "szám kell"))
            for k in ("t", "df", "t_crit"):
                if k in c and c[k] is not None and not _num(c[k]):
                    out.append(_f(ptr("categories", i, k), "szám vagy null kell"))
            for k in ("t_c_point_threshold", "welch_significant", "sampling_signal"):
                if k in c and not isinstance(c[k], bool):
                    out.append(_f(ptr("categories", i, k), "logikai érték kell"))
    return _rec("V01", "Séma és kulcs-fehérlista", out, "a szerkezet a specifikáció szerinti")


# ---------------------------------------------------------------- V02
def v02_fingerprint(r: dict) -> dict:
    name = "Eredmény-lenyomat"
    if not isinstance(r, dict) or not isinstance(r.get("fingerprint"), dict):
        return _skip("V02", name, "nincs fingerprint")
    fp = r["fingerprint"]
    body = {k: v for k, v in r.items() if k != "fingerprint"}
    out = []
    if fp.get("algorithm") != "sha256":
        out.append(_f(ptr("fingerprint", "algorithm"), "nem sha256"))
    got = sha256(body)
    if fp.get("result") != got:
        out.append(_f(ptr("fingerprint", "result"), "az újraszámolt lenyomat eltér"))
    return _rec("V02", name, out, "a lenyomat újraszámítva egyezik")


# ---------------------------------------------------------------- V03
def v03_config(r: dict, cfg: dict | None) -> dict:
    name = "Konfiguráció-lenyomat és paraméter-egyezés"
    if cfg is None:
        return _skip("V03", name, "konfiguráció nem adott")
    out = []
    try:
        canon = canonical_config(cfg)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return _rec("V03", name, [_f("", f"a konfiguráció nem értelmezhető: {type(exc).__name__}")])
    p = r["parameters"]
    if p["config_sha256"] != sha256(canon):
        out.append(_f(ptr("parameters", "config_sha256"), "a konfiguráció lenyomata eltér"))
    for key in ("weights", "level_max", "band_width", "min_cell"):
        if p[key] != canon[key]:
            out.append(_f(ptr("parameters", key), "eltér a konfigurációtól"))
    return _rec("V03", name, out, "a konfiguráció lenyomata és a paraméterek egyeznek")


# ---------------------------------------------------------------- V04
def v04_version(r: dict) -> dict:
    out = []
    if r["method_id"] not in KNOWN_METHODS:
        out.append(_f(ptr("method_id"), "ismeretlen módszerazonosító"))
    if not re.fullmatch(r"\d+\.\d+\.\d+", r["core_version"]):
        out.append(_f(ptr("core_version"), "nem szemantikus verziószám"))
    if r["evidence_level"] != "COMPUTED_MEASURED":
        out.append(_f(ptr("evidence_level"), "nem COMPUTED_MEASURED"))
    if r["legal_status"] != "REVIEW_REQUIRED":
        out.append(_f(ptr("legal_status"), "nem REVIEW_REQUIRED"))
    return _rec("V04", "Módszer, verzió és státuszjelölések", out, "ismert módszer és megengedett jelölések")


# ---------------------------------------------------------------- V05
def v05_suppression(r: dict) -> dict:
    out = []
    for i, c in enumerate(r["categories"]):
        if c["suppressed"] and set(c) != CAT_SUPPRESSED:
            out.append(_f(ptr("categories", i), "elnyomott kategória számadatot tartalmaz"))
    return _rec("V05", "Elnyomási invariáns", out, "az elnyomott kategóriák nem tartalmaznak számadatot")


# ---------------------------------------------------------------- V06
def v06_min_cell(r: dict) -> dict:
    out = []
    mc = r["parameters"]["min_cell"]
    if not _int(mc) or mc < 5:
        out.append(_f(ptr("parameters", "min_cell"), "a cellaminimum 5 alatt van vagy nem egész"))
        return _rec("V06", "Cellaminimum", out)
    for i, c in enumerate(r["categories"]):
        if not c["suppressed"]:
            for k in ("n_f", "n_m"):
                if c[k] < mc:
                    out.append(_f(ptr("categories", i, k), f"közölt kategória a cellaminimum alatt ({mc})"))
    return _rec("V06", "Cellaminimum", out, "minden közölt kategória eléri a cellaminimumot, és az nem kisebb 5-nél")


def _reported(r):
    return [(i, c) for i, c in enumerate(r["categories"]) if not c["suppressed"]]


# ---------------------------------------------------------------- V07
def v07_threshold(r: dict) -> dict:
    out = []
    tg = r["parameters"]["trigger_gap"]
    for i, c in _reported(r):
        if abs(c["gap"] - tg) <= 6e-7:
            continue  # a kerekítés miatt nem eldönthető
        if c["t_c_point_threshold"] != (c["gap"] >= tg):
            out.append(_f(ptr("categories", i, "t_c_point_threshold"), "nem egyezik a (gap ≥ küszöb) feltétellel"))
    return _rec("V07", "Küszöbérintés (T_c) konzisztenciája", out, "a küszöbérintés egyezik a bérrés és a küszöb viszonyával")


# ---------------------------------------------------------------- V08
def v08_welch(r: dict) -> dict:
    out = []
    for i, c in _reported(r):
        t, tc = c["t"], c["t_crit"]
        if t is None or tc is None:
            if c["welch_significant"]:
                out.append(_f(ptr("categories", i, "welch_significant"), "t nélkül nem lehet szignifikáns"))
            continue
        if abs(t - tc) <= 1.5e-4:
            continue
        if c["welch_significant"] != (t > tc):
            out.append(_f(ptr("categories", i, "welch_significant"), "nem egyezik a (t > t_crit) feltétellel"))
    return _rec("V08", "Welch-jelzés konzisztenciája", out, "a szignifikancia egyezik a t és a kritikus érték viszonyával")


# ---------------------------------------------------------------- V09
def v09_tcrit(r: dict) -> dict:
    out = []
    alpha = r["parameters"]["alpha"]
    if not (_fin(alpha) and 0 < alpha < 0.5):
        return _rec("V09", "Kritikus t-érték újraszámítása", [_f(ptr("parameters", "alpha"), "alpha 0 és 0,5 között legyen")])
    for i, c in _reported(r):
        t, df, tc = c["t"], c["df"], c["t_crit"]
        if df is None and t is None and tc is None:
            continue
        if df is None or t is None or tc is None:
            out.append(_f(ptr("categories", i), "t, df és t_crit együtt null vagy együtt szám"))
            continue
        if not (_fin(df) and df > 0 and _fin(tc)):
            out.append(_f(ptr("categories", i, "df"), "érvénytelen szabadságfok vagy kritikus érték"))
            continue
        try:
            q = upper_quantile(alpha, df)
            slope = abs(upper_quantile(alpha, df + 1e-3) - q) / 1e-3
        except ValueError:
            out.append(_f(ptr("categories", i, "df"), "a kritikus érték nem számítható"))
            continue
        tol = 2e-4 + slope * 5.5e-4
        if abs(q - tc) > tol:
            out.append(_f(ptr("categories", i, "t_crit"), f"az újraszámolt érték {q:.4f}, a közölt {tc}"))
    return _rec("V09", "Kritikus t-érték újraszámítása", out, "a kritikus értékek egyeznek a független számítással")


# ---------------------------------------------------------------- V10
def v10_signal(r: dict) -> dict:
    out = []
    for i, c in _reported(r):
        if c["sampling_signal"] != (c["t_c_point_threshold"] and c["welch_significant"]):
            out.append(_f(ptr("categories", i, "sampling_signal"), "nem egyezik a (T_c ∧ Welch) feltétellel"))
    return _rec("V10", "Mintavételi jelzés konzisztenciája", out, "a jelzés egyezik a küszöbérintés és a Welch-próba együttesével")


# ---------------------------------------------------------------- V11
def v11_summary(r: dict) -> dict:
    out = []
    s, rep = r["summary"], _reported(r)
    want = {
        "categories_total": len(r["categories"]),
        "categories_reported": len(rep),
        "categories_suppressed": len(r["categories"]) - len(rep),
        "point_threshold_hits": sum(c["t_c_point_threshold"] for _, c in rep),
        "sampling_signals": sum(c["sampling_signal"] for _, c in rep),
    }
    for k, v in want.items():
        if s[k] != v:
            out.append(_f(ptr("summary", k), f"újraszámolva {v}, közölve {s[k]}"))
    p0s = [c["p_point_trigger_if_no_gap"] for _, c in rep]
    exp = sum(p0s)
    anyp = 1.0 - math.prod(1.0 - p for p in p0s) if p0s else 0.0
    tol = 2e-4 + 5e-7 * len(p0s)
    if not _fin(s["expected_point_hits_if_no_gap"]) or abs(s["expected_point_hits_if_no_gap"] - exp) > tol:
        out.append(_f(ptr("summary", "expected_point_hits_if_no_gap"), f"újraszámolva {exp:.4f}"))
    if not _fin(s["p_any_point_hit_if_no_gap"]) or abs(s["p_any_point_hit_if_no_gap"] - anyp) > tol:
        out.append(_f(ptr("summary", "p_any_point_hit_if_no_gap"), f"újraszámolva {anyp:.4f}"))
    return _rec("V11", "Összegzés újraszámítása", out, "az összegzés egyezik a kategóriák újraszámolt összesítésével")


# ---------------------------------------------------------------- V12
def _phi(x: float) -> float:
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def v12_probabilities(r: dict) -> dict:
    out = []
    tg = r["parameters"]["trigger_gap"]
    if not (_fin(tg) and 0 < tg < 1):
        return _rec("V12", "Valószínűségek újraszámítása", [_f(ptr("parameters", "trigger_gap"), "a küszöb 0 és 1 között legyen")])
    z = -math.log(1.0 - tg)
    for i, c in _reported(r):
        se, p0 = c["se_log"], c["p_point_trigger_if_no_gap"]
        if not (_fin(se) and _fin(p0)):
            continue
        if se < 5e-7:
            continue  # a kerekített SE-ből nem rekonstruálható
        want = 1.0 - _phi(z / se)
        if abs(want - p0) > 5e-5:
            out.append(_f(ptr("categories", i, "p_point_trigger_if_no_gap"), f"újraszámolva {want:.6f}, közölve {p0}"))
    return _rec("V12", "Valószínűségek újraszámítása", out, "a kategóriánkénti valószínűségek egyeznek az se_log-ból számolttal")


# ---------------------------------------------------------------- V13
def v13_bands(r: dict) -> dict:
    out = []
    w = r["parameters"]["band_width"]
    if not (_fin(w) and w > 0):
        return _rec("V13", "Sávszerkezet", [_f(ptr("parameters", "band_width"), "pozitív szám kell")])
    prev = 0
    for i, c in enumerate(r["categories"]):
        g = c["grade"]
        if g < 1 or g <= prev:
            out.append(_f(ptr("categories", i, "grade"), "a kategóriák sorszáma nem szigorúan növekvő, vagy 1 alatti"))
        prev = max(prev, g)
        want = [(g - 1) * w, g * w]
        got = c["score_range"]
        if any(abs(a - b) > 1e-5 for a, b in zip(want, got)):
            out.append(_f(ptr("categories", i, "score_range"), f"a sávhatár nem (g−1)·w, g·w; várt {want}"))
    return _rec("V13", "Sávszerkezet", out, "a sávhatárok a sávszélességből következnek, a sorszámok növekvők")


# ---------------------------------------------------------------- V14
def v14_config_sanity(r: dict, cfg: dict | None) -> dict:
    out = []
    p = r["parameters"]
    w, lm = p["weights"], p["level_max"]
    if not (isinstance(w, list) and w and all(_fin(x) and x >= 0 for x in w)) or abs(sum(w) - 1.0) > 1e-9:
        out.append(_f(ptr("parameters", "weights"), "a súlyok nemnegatívak, összegük 1 legyen"))
    elif isinstance(lm, list):
        if len(lm) != len(w) or not all(_fin(x) and x > 0 for x in lm):
            out.append(_f(ptr("parameters", "level_max"), "a lista hossza egyezzen a súlyokéval, elemei pozitívak legyenek"))
    elif not (_fin(lm) and lm > 0):
        out.append(_f(ptr("parameters", "level_max"), "pozitív szám vagy lista kell"))
    if p["trigger_gap"] != 0.05:
        out.append(_f(ptr("parameters", "trigger_gap"), "a pilot küszöbe 0,05"))
    if p["alpha"] != 0.05:
        out.append(_f(ptr("parameters", "alpha"), "a pilot szignifikanciaszintje 0,05"))
    if cfg is not None and not out:
        try:
            cc = canonical_config(cfg)
            maxes = cc["level_max"] if isinstance(cc["level_max"], list) else [cc["level_max"]] * len(cc["weights"])
            for jid, lv in cc["jobs"].items():
                if len(lv) != len(cc["weights"]) or any(not (0 <= x <= m) for x, m in zip(lv, maxes)):
                    out.append(_f(ptr("jobs", jid), "a szintek hossza vagy tartománya hibás"))
        except (KeyError, TypeError, ValueError, AttributeError):
            out.append(_f("", "a konfiguráció nem értelmezhető"))
    return _rec("V14", "Konfiguráció-épség", out, "a súlyok, skálák és küszöbök megfelelők")


# ---------------------------------------------------------------- V15
def v15_sign(r: dict) -> dict:
    out = []
    for i, c in _reported(r):
        g, t = c["gap"], c["t"]
        if t is None:
            continue
        if (g > 0.02 and t < 0) or (g < -0.02 and t > 0):
            out.append(_f(ptr("categories", i), "a bérrés és a t előjele ellentétes (heurisztika)"))
    return _rec("V15", "Előjel-plauzibilitás", out, "nincs ellentétes előjelű bérrés–t pár", warn=True)


# ---------------------------------------------------------------- V16
def v16_excluded(r: dict) -> dict:
    out = []
    mc = r["parameters"]["min_cell"]
    for k, v in r["excluded"].items():
        if _int(v):
            if v < 0 or 0 < v < mc:
                out.append(_f(ptr("excluded", k), "kis darabszám nem közölhető pontosan, „<k” alak kell"))
        elif isinstance(v, str) and v != f"<{mc}":
            out.append(_f(ptr("excluded", k), "érvénytelen darabszám-alak"))
    return _rec("V16", "Kizárt darabszámok védelme", out, "a kis darabszámok „<k” alakban szerepelnek")


# ---------------------------------------------------------------- V17
def v17_numbers(r: dict) -> dict:
    out = []
    for i, c in _reported(r):
        for k in ("gap", "se_log", "p_point_trigger_if_no_gap", "t", "df", "t_crit"):
            v = c[k]
            if v is not None and not _fin(v):
                out.append(_f(ptr("categories", i, k), "NaN vagy végtelen érték"))
        if _fin(c["gap"]) and not (-1.0 < c["gap"] <= 1.0):
            out.append(_f(ptr("categories", i, "gap"), "a bérrés a (−1, 1] tartományon kívül van"))
        if _fin(c["se_log"]) and not (0.0 <= c["se_log"] < 5.0):
            out.append(_f(ptr("categories", i, "se_log"), "ésszerűtlen standard hiba"))
        if _fin(c["p_point_trigger_if_no_gap"]) and not (0.0 <= c["p_point_trigger_if_no_gap"] <= 1.0):
            out.append(_f(ptr("categories", i, "p_point_trigger_if_no_gap"), "valószínűség a [0, 1] tartományon kívül"))
        if c["t"] is not None and _fin(c["t"]) and abs(c["t"]) > 1e3:
            out.append(_f(ptr("categories", i, "t"), "ésszerűtlen nagyságrend"))
    for k in ("expected_point_hits_if_no_gap", "p_any_point_hit_if_no_gap"):
        if not _fin(r["summary"][k]):
            out.append(_f(ptr("summary", k), "NaN vagy végtelen érték"))
    return _rec("V17", "Számok épsége", out, "minden szám véges és ésszerű tartományban van")


# ---------------------------------------------------------------- V18
def _strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(k, path + "/" + str(k) + "[kulcs]") if isinstance(k, str) else ()
            yield from _strings(v, path + ptr(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, path + ptr(i))


def v18_text(r, cfg: dict | None) -> dict:
    out = []
    targets = [("", r)] + ([("/config", cfg)] if cfg is not None else [])
    for base, obj in targets:
        for path, s in _strings(obj):
            if _HEX64.match(s):
                continue
            where = base + path
            if _EMAIL.search(s):
                out.append(_f(where, "e-mail-cím jellegű szöveg"))
            if _URL.search(s):
                out.append(_f(where, "URL jellegű szöveg"))
            if _LONG_DIGITS.search(s):
                out.append(_f(where, "hosszú számsor (azonosító-gyanú)"))
            if _INSTRUCTION.search(s):
                out.append(_f(where, "utasításszerű szöveg (promptinjekció-gyanú)"))
    return _rec("V18", "Szabad szöveges mezők biztonsága", out, "nincs azonosító-, URL- vagy utasításszerű minta")


DEPENDENT = [("V03", "Konfiguráció-lenyomat és paraméter-egyezés"), ("V04", "Módszer, verzió és státuszjelölések"),
             ("V05", "Elnyomási invariáns"), ("V06", "Cellaminimum"), ("V07", "Küszöbérintés (T_c) konzisztenciája"),
             ("V08", "Welch-jelzés konzisztenciája"), ("V09", "Kritikus t-érték újraszámítása"),
             ("V10", "Mintavételi jelzés konzisztenciája"), ("V11", "Összegzés újraszámítása"),
             ("V12", "Valószínűségek újraszámítása"), ("V13", "Sávszerkezet"), ("V14", "Konfiguráció-épség"),
             ("V15", "Előjel-plauzibilitás"), ("V16", "Kizárt darabszámok védelme"), ("V17", "Számok épsége")]


def run_all(result, cfg: dict | None = None) -> list[dict]:
    """Minden ellenőrzés futtatása. Szerkezeti hiba (V01) esetén a függő ellenőrzések SKIPPED jelzést kapnak."""
    records = [v01_schema(result), v02_fingerprint(result) if isinstance(result, dict) else _skip("V02", "Eredmény-lenyomat", "nincs objektum")]
    if records[0]["status"] != "PASS":
        records += [_skip(i, n, "a V01 szerkezeti hibája miatt nem értékelhető") for i, n in DEPENDENT]
    else:
        records += [v03_config(result, cfg), v04_version(result), v05_suppression(result), v06_min_cell(result),
                    v07_threshold(result), v08_welch(result), v09_tcrit(result), v10_signal(result),
                    v11_summary(result), v12_probabilities(result), v13_bands(result), v14_config_sanity(result, cfg),
                    v15_sign(result), v16_excluded(result), v17_numbers(result)]
    records.append(v18_text(result, cfg) if isinstance(result, (dict, list)) else _skip("V18", "Szabad szöveges mezők biztonsága", "nincs objektum"))
    return records
