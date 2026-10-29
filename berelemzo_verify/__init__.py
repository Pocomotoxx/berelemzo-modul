"""Bérelemző eredmény-ellenőrző (L1): determinisztikus, MI-mentes, a Bérelemzőtől független ellenőrzések.

Az ellenőrző SZÁNDÉKOSAN nem importálja a `berelemzo` csomagot, és saját t-eloszlást használ, hogy a mag hibája
ne másolódjon át az ellenőrzésbe (N-verziós elv). Csak a szabványos könyvtárat használja.

Amit vizsgál: a Bérelemző eredményfájljának (és opcionálisan a konfigurációnak) belső épségét és konzisztenciáját.
Amit NEM vizsgál: a nyers adatot, a módszertan helyességét és a jogi megfelelést. A „nincs eltérés” nem azonos
azzal, hogy „helyes”.
"""

__version__ = "0.1.0"
VERIFIER_ID = "berelemzo_verify/1"
