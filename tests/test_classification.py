"""
Test de capacité : on envoie un seul batch de N×50 produits à Gemini
pour déterminer jusqu'où le modèle peut aller sans tronquer le JSON.
"""
import csv
import json
import os
import random
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))
API_KEY = os.getenv("GOOGLE_AI_API_KEY")

random.seed(42)

BRANDS   = ["Sony", "Samsung", "Apple", "LG", "Bose", "Logitech", "Razer", "Philips",
            "Anker", "TP-Link", "Asus", "Dell", "JBL", "Roborock", "Garmin", "DJI",
            "Canon", "Nikon", "Jabra", "SteelSeries", "Corsair", "Elgato", "Rode",
            "Withings", "Netatmo", "Somfy", "Nanoleaf", "Govee", "Hisense", "TCL"]
ADJECTIVES = ["Pro", "Ultra", "Max", "Elite", "Plus", "Advanced", "Smart", "Mini",
              "Slim", "Portable", "Wireless", "Premium", "Compact", "Turbo", "Neo"]
PRODUCT_NOUNS = [
    "Casque audio", "Enceinte Bluetooth", "Écran 4K", "Souris gaming", "Clavier mécanique",
    "Webcam HD", "Microphone USB", "Chargeur GaN", "Hub USB-C", "Routeur WiFi",
    "Robot aspirateur", "Ampoule connectée", "Caméra IP", "Montre connectée", "Drone",
    "Batterie externe", "Barre de son", "Réfrigérateur connecté", "Projecteur", "NAS",
    "Imprimante laser", "Tablette tactile", "Casque gaming", "Tapis de souris XXL",
    "Station de charge", "Clé USB", "Disque SSD", "Sonnette vidéo", "Thermostat connecté",
    "Bracelet fitness", "Appareil photo", "Téléviseur OLED", "Prise connectée",
    "Lampe de bureau", "Bandeau LED", "Chaise ergonomique", "Boîte domotique",
]
CATEGORIES = ["Audio", "Gaming", "Informatique", "Maison connectée", "Photo", "Mobile",
              "Télévision", "Éclairage", "Sécurité", "Mobilier", "Réseau", "Sport"]

def random_product(pid: int) -> dict:
    noun = random.choice(PRODUCT_NOUNS)
    brand = random.choice(BRANDS)
    adj = random.choice(ADJECTIVES)
    model_num = f"{random.choice('ABCDEFGHJKMNPQRSTVWXYZ')}{random.randint(10,99)}"
    gen = random.randint(1, 5)
    return {
        "id": str(pid),
        "name": f"{brand} {noun} {adj} {model_num} Gen{gen}",
        "brand": brand,
        "category_slug": random.choice(CATEGORIES).lower().replace(" ", "-"),
        "merchant_category": random.choice(CATEGORIES),
        "description": f"{noun} {adj.lower()} {brand}, génération {gen}, modèle {model_num}",
    }

# ── Encodage compact ──────────────────────────────────────────────────────────
PRODUCT_TYPES = [
    "smartphone","televiseur","ecouteurs_tws","casque_audio","casque_gaming",
    "souris_gaming","souris","clavier_gaming","clavier","ecran_gaming",
    "ecran_moniteur","pc_portable","enceinte_bluetooth","enceinte_hifi","barre_de_son",
    "ampoule_connectee","robot_aspirateur","chargeur_rapide","powerbank","hub_usb",
    "webcam","microphone","nas","routeur_wifi","camera_surveillance","sonnette_video",
    "smartwatch","bracelet_sport","appareil_photo","drone","camera_action",
    "bandeau_led","chaise_bureau_ergo","autre",
]
ROOMS          = ["chambre","bureau","salon","cuisine","exterieur","universel"]
USE_CATEGORIES = ["gaming","audio_hifi","informatique","mobile_smartphone",
                  "domotique","eclairage","tv_cinema","accessoire"]
NICHES         = ["gaming_setup","home_office_setup","mobile_nomade","smart_home",
                  "audio_hi_fi","living_room_storage","cozy_lighting","outdoor_living"]

def _codes(lst): return " ".join(f"{i}={v}" for i, v in enumerate(lst))

SYSTEM = (
    "Tu es un classificateur de produits e-commerce français.\n"
    "Pour chaque produit JSON, réponds UNIQUEMENT avec ce JSON compact :\n"
    '{"results":[{"i":"ID","t":N,"r":N,"u":N,"n":[N,...]}]}\n\n'
    f"t (product_type): {_codes(PRODUCT_TYPES)}\n"
    f"r (room):         {_codes(ROOMS)}\n"
    f"u (use_category): {_codes(USE_CATEGORIES)}\n"
    f"n (niches 0-3):   {_codes(NICHES)}\n"
)

def decode_result(item: dict) -> dict | None:
    """Convertit un résultat compact {i,t,r,u,n} en dict lisible."""
    try:
        return {
            "id":           str(item["i"]),
            "product_type": PRODUCT_TYPES[int(item["t"])],
            "room":         ROOMS[int(item["r"])],
            "use_category": USE_CATEGORIES[int(item["u"])],
            "niches":       [NICHES[int(x)] for x in (item.get("n") or []) if 0 <= int(x) < len(NICHES)],
        }
    except (KeyError, IndexError, ValueError):
        return None

# Tailles à tester : 50, 100, 200, 300, 500, 800, 1000
MULTIPLIERS = [1, 2, 4, 6, 10, 16, 20]
URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={API_KEY}"
OUTPUT_CSV = os.path.join(os.path.dirname(__file__), "output", "classification_results.csv")
os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)

csv_rows = []
summary_rows = []

for mult in MULTIPLIERS:
    # Générer N produits entièrement aléatoires (noms/marques uniques → pas de déduplication)
    n_sent = mult * 50
    batch = [random_product(pid) for pid in range(1, n_sent + 1)]
    expected_ids = {str(p["id"]) for p in batch}

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(batch, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 65536},
    }

    t0 = time.time()
    try:
        req = urllib.request.Request(
            URL,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            d = json.load(resp)
    except Exception as e:
        elapsed = round(time.time() - t0, 2)
        print(f"[×{mult:02d} | {n_sent:4d} produits] ❌ Erreur HTTP : {e}  ({elapsed}s)")
        summary_rows.append({"multiplier": mult, "n_sent": n_sent, "n_returned": 0,
                              "n_ok": 0, "n_missing": n_sent, "elapsed_s": elapsed, "status": "HTTP_ERROR"})
        continue

    elapsed = round(time.time() - t0, 2)

    if "candidates" not in d:
        print(f"[×{mult:02d} | {n_sent:4d} produits] ❌ Réponse inattendue  ({elapsed}s)")
        summary_rows.append({"multiplier": mult, "n_sent": n_sent, "n_returned": 0,
                              "n_ok": 0, "n_missing": n_sent, "elapsed_s": elapsed, "status": "BAD_RESPONSE"})
        continue

    try:
        text = d["candidates"][0]["content"]["parts"][0]["text"]
        data, _ = json.JSONDecoder().raw_decode(text.strip())
        results = data["results"]
    except Exception as e:
        print(f"[×{mult:02d} | {n_sent:4d} produits] ❌ Parse JSON échoué : {e}  ({elapsed}s)")
        summary_rows.append({"multiplier": mult, "n_sent": n_sent, "n_returned": 0,
                              "n_ok": 0, "n_missing": n_sent, "elapsed_s": elapsed, "status": "JSON_PARSE_ERROR"})
        continue

    # Validation + décodage
    n_ok = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        if str(item.get("i", "")) not in expected_ids:
            continue
        decoded = decode_result(item)
        if decoded is None:
            continue
        n_ok += 1
        csv_rows.append({
            "multiplier": mult,
            "id": decoded["id"],
            "product_type": decoded["product_type"],
            "room": decoded["room"],
            "use_category": decoded["use_category"],
            "niches": "|".join(decoded["niches"]),
        })

    n_returned = len(results)
    n_missing = n_sent - n_ok
    pct = round(100 * n_ok / n_sent)
    status = "✅" if n_ok == n_sent else ("⚠️ " if n_ok > 0 else "❌")
    print(
        f"[×{mult:02d} | {n_sent:4d} produits] {status}"
        f"  retournés={n_returned}  valides={n_ok}/{n_sent} ({pct}%)"
        f"  manquants={n_missing}  {elapsed}s"
    )
    summary_rows.append({"multiplier": mult, "n_sent": n_sent, "n_returned": n_returned,
                         "n_ok": n_ok, "n_missing": n_missing, "elapsed_s": elapsed,
                         "status": "OK" if n_ok == n_sent else "PARTIAL" if n_ok > 0 else "EMPTY"})

# CSV résultats détaillés
with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["multiplier", "id", "product_type", "room", "use_category", "niches"])
    writer.writeheader()
    writer.writerows(csv_rows)

# CSV résumé
summary_csv = OUTPUT_CSV.replace("classification_results.csv", "classification_summary.csv")
with open(summary_csv, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["multiplier", "n_sent", "n_returned", "n_ok", "n_missing", "elapsed_s", "status"])
    writer.writeheader()
    writer.writerows(summary_rows)

print(f"\n📄 Résultats  → {OUTPUT_CSV}")
print(f"📊 Résumé     → {summary_csv}")
