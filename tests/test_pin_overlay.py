#!/usr/bin/env python3
"""
test_pin_overlay.py — Rendu des overlays sur image template fixe.

Applique le texte overlay sur une image de fond réutilisable  
sans rien générer. Vérifier si le titre s'inscrit bien dans l'image.

Usage :
    python tests/test_pin_overlay.py --text "5 achats qui révolutionnent votre bureau"
    python tests/test_pin_overlay.py --from-outputs          # lit tous les pin_*.txt générés
    python tests/test_pin_overlay.py --template mon_fond.jpg # fond custom (1-shot)
    python tests/test_pin_overlay.py --from-outputs --template fond.jpg

Image template par défaut : tests/template_bg.jpg  (créée auto si absente)
Outputs : tests/output/overlay_preview/
"""
import sys, re, argparse, random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError:
    print("❌ Pillow requis : pip install Pillow")
    sys.exit(1)

from settings import FONTS_DIR

# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES
# ══════════════════════════════════════════════════════════════════════════════
PIN_W, PIN_H = 1000, 1500
TESTS_DIR    = Path(__file__).parent
OUTPUT_DIR   = TESTS_DIR / "output" / "overlay_preview"
TEMPLATE_PATH = TESTS_DIR / "template_bg.jpg"

# ══════════════════════════════════════════════════════════════════════════════
# FONTS — Caveat uniquement (même logique que create_and_post_top_products.py)
# ══════════════════════════════════════════════════════════════════════════════
_TTF_MAGIC = (b"\x00\x01\x00\x00", b"\x74\x72\x75\x65", b"\x4F\x54\x54\x4F")


def _valid_ttf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 4:
        return False
    return path.read_bytes()[:4] in _TTF_MAGIC


def _load_caveat_font(size: int) -> ImageFont.FreeTypeFont:
    for name in ("Caveat-Bold.ttf", "Caveat-Regular.ttf"):
        p = FONTS_DIR / name
        if _valid_ttf(p):
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                pass
    for fallback in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                     "/System/Library/Fonts/Helvetica.ttc",
                     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(fallback, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _tw(font: ImageFont.FreeTypeFont, text: str) -> float:
    dummy = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    return dummy.textlength(text, font=font)


def _wrap_overlay(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    words = text.upper().split()
    lines, cur = [], []
    for word in words:
        candidate = " ".join(cur + [word])
        if _tw(font, candidate) > max_w and cur:
            lines.append(" ".join(cur))
            cur = [word]
        else:
            cur.append(word)
    if cur:
        lines.append(" ".join(cur))
    return lines or [text.upper()]


def _autofit(text: str, max_w: int, max_h: int,
             start: int = 190, minimum: int = 50, spacing: float = 1.20) -> tuple:
    """Retourne (font, lines, line_h, fsize) en diminuant la taille jusqu'à ce que ça tienne."""
    for size in range(start, minimum - 1, -2):
        font = _load_caveat_font(size)
        words = text.upper().split()
        if max(_tw(font, w) for w in words) > max_w:
            continue
        lines = _wrap_overlay(text, font, max_w)
        line_h = int(size * spacing)
        if len(lines) * line_h <= max_h:
            return font, lines, line_h, size
    # minimum absolu
    font = _load_caveat_font(minimum)
    lines = _wrap_overlay(text, font, max_w)
    line_h = int(minimum * spacing)
    return font, lines, line_h, minimum


# ══════════════════════════════════════════════════════════════════════════════
# OVERLAY RENDERER — identique au workflow de production
# ══════════════════════════════════════════════════════════════════════════════
PALETTES = [
    ((10, 8, 6, 230), (255, 255, 255, 255), (20, 15, 10, 255)),
    ((38, 35, 55, 225), (255, 240, 200, 255), (20, 15, 40, 255)),
    ((15, 45, 35, 225), (245, 235, 210, 255), (10, 30, 20, 255)),
    ((90, 40, 35, 220), (255, 240, 215, 255), (60, 20, 15, 255)),
    ((155, 100, 55, 215), (255, 255, 255, 255), (90, 55, 20, 255)),
    ((55, 75, 90, 225), (240, 225, 200, 255), (25, 40, 55, 255)),
    ((130, 90, 85, 220), (255, 250, 240, 255), (80, 50, 45, 255)),
    ((30, 50, 65, 225), (210, 240, 220, 255), (15, 30, 45, 255)),
    ((75, 65, 55, 220), (255, 245, 220, 255), (40, 35, 25, 255)),
    ((180, 155, 120, 215), (30, 25, 15, 255), (120, 100, 70, 255)),
]


def apply_overlay(img: Image.Image, text: str, save_to: Path) -> dict:
    """
    Applique l'overlay Caveat sur l'image et la sauvegarde.
    Retourne les métriques de rendu (pour diagnostiquer le fit).
    """
    save_to.parent.mkdir(parents=True, exist_ok=True)
    img = img.convert("RGBA")
    W, H = img.size

    # ── Paramètres de zone (identique à _add_text_overlay) ──────────────────
    BAND_H   = int(H * 0.48)
    MARGIN_X = int(W * 0.07)
    PAD_TOP  = int(H * 0.04)
    PAD_BOT  = int(H * 0.04)
    MAX_TXT_W = W - 2 * MARGIN_X
    MAX_TXT_H = BAND_H - PAD_TOP - PAD_BOT

    # ── Gradient sombre en haut ──────────────────────────────────────────────
    grad_pixels = []
    for row in range(BAND_H):
        t = row / BAND_H
        alpha = int(160 * (1.0 - t ** 0.55))
        grad_pixels.append((8, 6, 5, alpha))
    grad_col = Image.new("RGBA", (1, BAND_H))
    grad_col.putdata(grad_pixels)
    gradient = grad_col.resize((W, BAND_H), Image.Resampling.NEAREST)
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band.paste(gradient, (0, 0))
    img = Image.alpha_composite(img, band)

    # ── Autofit ──────────────────────────────────────────────────────────────
    font, lines, line_h, fsize = _autofit(text, MAX_TXT_W, MAX_TXT_H)
    block_h = len(lines) * line_h
    fits = block_h <= MAX_TXT_H

    # ── Palette et positions ─────────────────────────────────────────────────
    rng = random.Random(hash(text))
    blob_color, text_color, stroke_color = rng.choice(PALETTES)
    HL_PAD    = int(fsize * 0.20)
    HL_RADIUS = max(10, int(fsize * 0.22))
    INTER_GAP = int(fsize * 0.22)

    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_positions_rel, hl_boxes_rel = [], []
    y = 0
    for line in lines:
        lw = int(_tw(font, line))
        txt_x = (W - lw) // 2
        tbbox = dummy.textbbox((txt_x, y), line, font=font)
        text_positions_rel.append((txt_x, y))
        hl_boxes_rel.append([
            tbbox[0] - HL_PAD,
            tbbox[1] - HL_PAD + INTER_GAP // 2,
            tbbox[2] + HL_PAD,
            tbbox[3] + HL_PAD - INTER_GAP // 2,
        ])
        y += line_h

    actual_block_h = hl_boxes_rel[-1][3] - hl_boxes_rel[0][1]
    target_center_y = int(H * 0.35)
    shift = target_center_y - actual_block_h // 2 - hl_boxes_rel[0][1]

    text_positions = [(tx, ty + shift) for tx, ty in text_positions_rel]
    hl_boxes = [[hx0, hy0 + shift, hx1, hy1 + shift] for hx0, hy0, hx1, hy1 in hl_boxes_rel]

    # ── Highlight blobs ──────────────────────────────────────────────────────
    hl_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hl_draw = ImageDraw.Draw(hl_layer)
    for hx0, hy0, hx1, hy1 in hl_boxes:
        try:
            hl_draw.rounded_rectangle([hx0, hy0, hx1, hy1], radius=HL_RADIUS, fill=blob_color)
        except AttributeError:
            hl_draw.rectangle([hx0, hy0, hx1, hy1], fill=blob_color)
    img = Image.alpha_composite(img, hl_layer)

    # ── Ombre portée ─────────────────────────────────────────────────────────
    sh_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh_draw  = ImageDraw.Draw(sh_layer)
    sh_off   = max(3, fsize // 32)
    sh_blur  = max(4, fsize // 20)
    for (tx, ty), line in zip(text_positions, lines):
        sh_draw.text((tx + sh_off, ty + sh_off), line, font=font, fill=(0, 0, 0, 180))
    sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(radius=sh_blur))
    img = Image.alpha_composite(img, sh_layer)

    # ── Texte principal ───────────────────────────────────────────────────────
    draw     = ImageDraw.Draw(img)
    stroke_w = max(2, fsize // 55)
    for (tx, ty), line in zip(text_positions, lines):
        draw.text((tx, ty), line, font=font,
                  fill=text_color, stroke_width=stroke_w, stroke_fill=stroke_color)

    # ── Tiret décoratif ───────────────────────────────────────────────────────
    last_box_bottom = hl_boxes[-1][3]
    dash_y  = last_box_bottom + int(fsize * 0.25)
    dash_hw = int(W * 0.055)
    dash_cx = W // 2
    dash_th = max(2, fsize // 60)
    draw.line([(dash_cx - dash_hw, dash_y), (dash_cx + dash_hw, dash_y)],
              fill=(*text_color[:3], 190), width=dash_th)
    dot_r = dash_th + 1
    for dx in [dash_cx - dash_hw, dash_cx + dash_hw]:
        draw.ellipse([dx - dot_r, dash_y - dot_r, dx + dot_r, dash_y + dot_r],
                     fill=(*text_color[:3], 170))

    # ── Zone de fit visuelle (DEBUG) — rectangle rouge si déborde ────────────
    if not fits:
        debug_draw = ImageDraw.Draw(img)
        zone_y = int(H * 0.35) - MAX_TXT_H // 2
        debug_draw.rectangle(
            [MARGIN_X, zone_y, W - MARGIN_X, zone_y + MAX_TXT_H],
            outline=(255, 80, 80, 200), width=4,
        )

    # ── Sauvegarde ───────────────────────────────────────────────────────────
    img.convert("RGB").save(str(save_to), "JPEG", quality=95)

    return {
        "fits":      fits,
        "font_size": fsize,
        "lines":     lines,
        "n_lines":   len(lines),
        "line_h":    line_h,
        "block_h":   block_h,
        "max_h":     MAX_TXT_H,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TEMPLATE BACKGROUND
# ══════════════════════════════════════════════════════════════════════════════
def _make_default_gradient() -> Image.Image:
    """Gradient neutre chaud → simule une ambiance photo lifestyle."""
    img  = Image.new("RGB", (PIN_W, PIN_H))
    draw = ImageDraw.Draw(img)
    top, bot = (58, 52, 46), (108, 90, 76)
    for y in range(PIN_H):
        t = y / PIN_H
        r = int(top[0] + (bot[0] - top[0]) * t)
        g = int(top[1] + (bot[1] - top[1]) * t)
        b = int(top[2] + (bot[2] - top[2]) * t)
        draw.line([(0, y), (PIN_W, y)], fill=(r, g, b))
    return img


def load_template(template_arg: str | None) -> tuple[Image.Image, str]:
    """Charge le fond. Retourne (image, label source)."""
    # 1. Argument CLI prioritaire
    if template_arg:
        p = Path(template_arg)
        if p.exists():
            img = Image.open(p).convert("RGB").resize((PIN_W, PIN_H), Image.LANCZOS)
            return img, str(p)
        print(f"⚠️  Template introuvable : {p}  → gradient utilisé")

    # 2. Fichier par défaut dans tests/
    if TEMPLATE_PATH.exists():
        img = Image.open(TEMPLATE_PATH).convert("RGB").resize((PIN_W, PIN_H), Image.LANCZOS)
        return img, str(TEMPLATE_PATH)

    # 3. Gradient de secours (sauvegardé pour les prochains appels)
    img = _make_default_gradient()
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(TEMPLATE_PATH), "JPEG", quality=90)
    return img, f"gradient auto → {TEMPLATE_PATH}"


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION DES OVERLAYS DEPUIS LES OUTPUTS
# ══════════════════════════════════════════════════════════════════════════════
def read_overlays_from_outputs() -> list[tuple[str, str]]:
    """Parcourt tests/output/*/pin_*.txt et extrait les overlays."""
    items = []
    for pin_file in sorted((TESTS_DIR / "output").glob("*/pin_*.txt")):
        content = pin_file.read_text(encoding="utf-8", errors="replace")
        niche   = pin_file.parent.name
        slug    = pin_file.stem           # pin_01 / pin_02
        m = re.search(r"^OVERLAY IMAGE\n[-─]+\n(.+)$", content, re.MULTILINE)
        if m:
            items.append((f"{niche}/{slug}", m.group(1).strip()))
    return items


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rendu overlay texte sur image template — test visuel Pinterest"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text",        type=str,  help="Overlay texte à tester directement")
    group.add_argument("--from-outputs", action="store_true",
                       help="Lire les overlays depuis tests/output/*/pin_*.txt")
    parser.add_argument("--template", type=str, default=None,
                        help=f"Image de fond (défaut : {TEMPLATE_PATH})")
    args = parser.parse_args()

    bg, template_label = load_template(args.template)

    print(f"✦ Template  : {template_label}")
    print(f"✦ Dimension : {PIN_W}×{PIN_H} px")
    print(f"✦ Police    : Caveat-Bold  (assets/fonts/)")
    print(f"✦ Output    : {OUTPUT_DIR}")
    print()

    if args.text:
        items = [("custom_overlay", args.text)]
    else:
        items = read_overlays_from_outputs()
        if not items:
            print("❌ Aucun pin_*.txt trouvé dans tests/output/")
            print("   Lance d'abord :  python tests/test_pin_creation.py --no-image")
            sys.exit(1)
        print(f"→ {len(items)} overlay(s) détecté(s)\n")

    ok = warn = 0
    for slug, text in items:
        safe_name = re.sub(r"[^a-z0-9_-]", "_", slug.replace("/", "_").lower())
        out_path  = OUTPUT_DIR / f"{safe_name}.jpg"

        m = apply_overlay(bg.copy(), text, out_path)

        icon = "✅" if m["fits"] else "⚠️ "
        if m["fits"]:
            ok += 1
        else:
            warn += 1

        print(f"{icon}  {slug}")
        print(f"   Texte brut   : {text}")
        print(f"   Rendu uppercased : {' / '.join(m['lines'])}")
        print(f"   Police       : {m['font_size']}px  |  {m['n_lines']} ligne(s)")
        print(f"   Bloc texte   : {m['block_h']}px  /  {m['max_h']}px disponibles", end="")
        if not m["fits"]:
            print(f"  ← DÉBORDEMENT ({m['block_h'] - m['max_h']}px en trop)", end="")
        print(f"\n   Fichier      : {out_path.relative_to(TESTS_DIR)}\n")

    sep = "─" * 55
    print(sep)
    print(f"Résultat : {ok} ✅ fit  /  {warn} ⚠️  débordement")
    if warn == 0:
        print("Tous les overlays s'inscrivent correctement dans le cadre.")
    else:
        print("Les éléments ⚠️ ont un cadre rouge dessiné sur l'image pour visualiser le dépassement.")
    print(f"\nOuvrir les images : open {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
