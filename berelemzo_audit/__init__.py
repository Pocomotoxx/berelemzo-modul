"""Bérelemző megfelelőségi audit-motor: a bértranszparencia-auditkézikönyv kontrollkatalógusának determinisztikus, MI-mentes értékelése.

Bemenet: a beérkezett egyéni szintű adat (helyben), a pontozási konfiguráció, opcionálisan a Bérelemző eredménye és a
szervezet nyilatkozatai. Kimenet: kontrollonkénti értékelés, aggregált mutatók, az 5%-os küszöb kezelésének állapota és
a bértranszparencia-rekordtípusokkal kompatibilis aggregált rekordok. Egyéni sor soha nem kerül a kimenetbe.

Amit NEM tesz: jogi minősítést, bérkorrekciót vagy közzétételi döntést nem állapít meg. Minden kimenet REVIEW_REQUIRED.
"""

__version__ = "0.1.0"
AUDIT_ID = "berelemzo_audit/1"
