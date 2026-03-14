"""
Test de parallélisation Gemini : envoie N batches de 500 produits simultanément
avec retry automatique sur 429/503.
"""
import csv
import json
import os
import random
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env.local"))
API_KEY = os.getenv("GOOGLE_AI_API_KEY")

random.seed(99)

# ── Générateur produits ────────────────────────────────────────────────────────
BRANDS      = ["Sony","Samsung","Apple","LG","Bose","Logitech","Razer","Philips",
               "Anker","TP-Link","Asus","Dell","JBL","Roborock","Garmin","DJI"]
ADJECTIVES  = ["Pro","Ultra","Max","Elite","Plus","Smart","Mini","Slim","Turbo","Neo"]
NOUNS       = ["Casque audio","Enceinte Bluetooth","Écran 4K","Souris gaming","Clavier mécanique",
               "Webcam HD","Microphone USB","Chargeur GaN","Hub USB-C","Routeur WiFi",
               "Robot aspirateur","Ampoule connectée","Caméra IP","Montre connectée","Drone",
               "Batterie externe","Barre de son","Tablette tactile","Disque SSD","Sonnette vidéo"]
CATEGORIES  = ["Audio","Gaming","Informatique","Maison connectée","Photo","Mobile","Télévision"]

def random_batch(batch_id: int, size: int = 500) -> list[dict]:
    rng = random.Random(batch_id)
    return [{
        "id": str(batch_id * 10000 + i),
        "name": f"{rng.choice(BRANDS)} {rng.choice(NOUNS)} {rng.choice(ADJECTIVES)} "
                f"{rng.choice('ABCDEFGHJK')}{rng.randint(10,99)} Gen{rng.randint(1,5)}",
        "brand": rng.choice(BRANDS),
        "category_slug": rng.choice(CATEGORIES).lower().replace(" ", "-"),
        "merchant_category": rng.choice(CATEGORIES),
        "description": f"{rng.choice(NOUNS)} {rng.choice(ADJECTIVES).lower()}, modèle {rng.randint(100,999)}",
    } for i in range(size)]

# ── Encodage compact ───────────────────────────────────────────────────────────
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

def decode_result(item: dict) -> dict | None:
    """Convertit {i,t,r,u,n} compact en dict lisible."""
    try:
        return {
            "id":           str(item["i"]),
            "product_type": PRODUCT_TYPES[int(item["t"])],
            "room":         ROOMS[int(item["r"])],
            "use_category": USE_CATEGORIES[int(item["u"])],
            "niches":       "|".join(NICHES[int(x)] for x in (item.get("n") or [])
                                     if 0 <= int(x) < len(NICHES)),
        }
    except (KeyError, IndexError, ValueError):
        return None

SYSTEM = (
    "Tu es un classificateur de produits e-commerce français.\n"
    "Pour chaque produit JSON, réponds UNIQUEMENT avec ce JSON compact :\n"
    '{"results":[{"i":"ID","t":N,"r":N,"u":N,"n":[N,...]}]}\n\n'
    f"t (product_type): {_codes(PRODUCT_TYPES)}\n"
    f"r (room):         {_codes(ROOMS)}\n"
    f"u (use_category): {_codes(USE_CATEGORIES)}\n"
    f"n (niches 0-3):   {_codes(NICHES)}\n"
)

URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-preview:generateContent?key={API_KEY}"

# ── Appel API avec retry ───────────────────────────────────────────────────────
MAX_RETRIES = 3
# Délais de backoff en secondes par code d'erreur
BACKOFF = {429: [10, 20, 40], 503: [5, 10, 20]}

def call_gemini(batch_id: int, batch: list[dict]) -> dict:
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(batch, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 65536},
    }
    t0 = time.time()
    attempt = 0

    while attempt <= MAX_RETRIES:
        try:
            req = urllib.request.Request(
                URL,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                d = json.load(resp)

        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read().decode()[:120]
            elapsed_so_far = round(time.time() - t0, 2)

            if code in BACKOFF and attempt < MAX_RETRIES:
                wait = BACKOFF[code][attempt]
                print(f"  ⚠️   batch {batch_id:02d}  HTTP {code}  tentative {attempt+1}/{MAX_RETRIES}  "
                      f"→ retry dans {wait}s  ({elapsed_so_far}s écoulé)")
                time.sleep(wait)
                attempt += 1
                continue

            return {"batch_id": batch_id, "ok": False,
                    "error": f"HTTP {code}: {body}",
                    "elapsed": round(time.time() - t0, 2), "n_ok": 0,
                    "attempts": attempt + 1}

        except Exception as e:
            elapsed_so_far = round(time.time() - t0, 2)
            if attempt < MAX_RETRIES:
                wait = 5 * (attempt + 1)
                print(f"  ⚠️   batch {batch_id:02d}  {str(e)[:60]}  "
                      f"tentative {attempt+1}/{MAX_RETRIES}  → retry dans {wait}s  ({elapsed_so_far}s écoulé)")
                time.sleep(wait)
                attempt += 1
                continue
            return {"batch_id": batch_id, "ok": False, "error": str(e),
                    "elapsed": round(time.time() - t0, 2), "n_ok": 0,
                    "attempts": attempt + 1}

        # ── Parsing ────────────────────────────────────────────────────────────
        elapsed = round(time.time() - t0, 2)
        try:
            raw = d["candidates"][0]["content"]["parts"][0]["text"].strip()
            data, _ = json.JSONDecoder().raw_decode(raw)
            results = data["results"]
            rows = [decode_result(r) for r in results if isinstance(r, dict)]
            rows = [r for r in rows if r is not None]
            n_ok = len(rows)
            return {"batch_id": batch_id, "ok": True, "elapsed": elapsed,
                    "n_returned": len(results), "n_ok": n_ok, "n_sent": len(batch),
                    "attempts": attempt + 1, "rows": rows}
        except Exception as e:
            elapsed_so_far = round(time.time() - t0, 2)
            if attempt < MAX_RETRIES:
                wait = 5
                print(f"  ⚠️   batch {batch_id:02d}  parse error: {e}  "
                      f"tentative {attempt+1}/{MAX_RETRIES}  → retry dans {wait}s  ({elapsed_so_far}s écoulé)")
                time.sleep(wait)
                attempt += 1
                continue
            return {"batch_id": batch_id, "ok": False, "error": f"parse: {e}",
                    "elapsed": elapsed, "n_ok": 0, "attempts": attempt + 1}

    # Ne devrait pas arriver
    return {"batch_id": batch_id, "ok": False, "error": "max retries exceeded",
            "elapsed": round(time.time() - t0, 2), "n_ok": 0, "attempts": MAX_RETRIES + 1}

# ── Test ciblé : 4 workers × batch 500 → 5000 produits ───────────────────────
import math
BATCH_SIZE  = 500
N_WORKERS   = 4
TOTAL       = 5000

n_batches = math.ceil(TOTAL / BATCH_SIZE)
batches = [
    (idx, random_batch(idx, min(BATCH_SIZE, TOTAL - idx * BATCH_SIZE)))
    for idx in range(n_batches)
]

print(f"▶  {TOTAL} produits  ·  {n_batches} batches de ~{BATCH_SIZE}  ·  {N_WORKERS} workers en parallèle")
print(f"   Retry : jusqu'à {MAX_RETRIES}× par batch (backoff 429={BACKOFF[429]}, 503={BACKOFF[503]})")
print(f"   Théorie : ~{n_batches // N_WORKERS + (1 if n_batches % N_WORKERS else 0)} vague(s) × ~35s\n")

t_start = time.time()
results_all: list[dict] = []

with ThreadPoolExecutor(max_workers=N_WORKERS) as ex:
    futures = {ex.submit(call_gemini, bid, b): bid for bid, b in batches}
    for fut in as_completed(futures):
        r = fut.result()
        results_all.append(r)
        bid      = r["batch_id"]
        elapsed  = r["elapsed"]
        attempts = r.get("attempts", 1)
        retry_tag = f"  [retry ×{attempts-1}]" if attempts > 1 else ""
        if r["ok"]:
            print(f"  ✅  batch {bid:02d}  ✓{r['n_ok']}/{r['n_sent']}  {elapsed}s{retry_tag}")
        else:
            print(f"  ❌  batch {bid:02d}  {r.get('error','?')[:80]}  {elapsed}s{retry_tag}")

total_elapsed = round(time.time() - t_start, 2)
n_success    = sum(1 for r in results_all if r["ok"])
n_prod_ok    = sum(r.get("n_ok", 0) for r in results_all)
n_retried    = sum(1 for r in results_all if r.get("attempts", 1) > 1)
throughput   = round(n_prod_ok / total_elapsed) if total_elapsed > 0 else 0
avg_batch    = round(sum(r["elapsed"] for r in results_all) / len(results_all), 2)

# ── Export CSV ────────────────────────────────────────────────────────────────
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
OUTPUT_CSV = os.path.join(OUTPUT_DIR, "parallel_results.csv")

all_rows = []
for r in sorted(results_all, key=lambda x: x["batch_id"]):
    for row in r.get("rows", []):
        all_rows.append({**row, "batch_id": r["batch_id"]})

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=["batch_id", "id", "product_type", "room", "use_category", "niches"])
    writer.writeheader()
    writer.writerows(all_rows)

print(f"\n{'═'*60}")
print(f"  Batches réussis : {n_success}/{n_batches}")
print(f"  Avec retry      : {n_retried} batch(es)")
print(f"  Produits ok     : {n_prod_ok}/{TOTAL} ({round(100*n_prod_ok/TOTAL)}%)")
print(f"  Temps total     : {total_elapsed}s")
print(f"  Temps /batch    : {avg_batch}s")
print(f"  Débit           : {throughput} produits/s")
print(f"  → 13 458 produits estimé : ~{round(13458/throughput/60, 1)} min" if throughput else "")
print(f"{'═'*60}")
print(f"\n  📄 CSV → {OUTPUT_CSV}  ({len(all_rows)} lignes)")

