#!/usr/bin/env python3
"""
scrape_prices.py — Scraping massif et multi-sources de prix affiliés

Architecture en 4 couches :
  1. Adaptateurs par site (Amazon, Fnac, Cdiscount, Darty, eBay)
  2. Pool de proxies rotatifs avec retry exponentiel
  3. Queue async (asyncio + aiohttp) — N scrapes en parallèle
  4. Upsert Supabase + déclenchement revalidation Vercel ISR

Usage :
  # Tous les produits
  python scripts/scrape_prices.py

  # Un seul partenaire
  python scripts/scrape_prices.py --partner amazon_fr

  # Mode dry-run (pas d'écriture Supabase)
  python scripts/scrape_prices.py --dry-run

Dépendances :
  pip install aiohttp beautifulsoup4 supabase python-dotenv lxml fake-useragent

Stratégies anti-détection :
  - Rotation user-agent (fake_useragent)
  - Délais aléatoires entre requêtes (2–8s)
  - Proxies SOCKS5/HTTP rotatifs (optionnel, via SCRAPER_PROXY_LIST)
  - Headers réalistes (Accept-Language, Referer, sec-ch-ua, etc.)
  - API ScrapingBee en fallback si blocage détecté (429/503)
"""

import asyncio
import json
import logging
import os
import random
import re
import sys
import time
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, quote_plus

import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env.local"))

try:
    from supabase import create_client
except ImportError:
    print("pip install supabase")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scraper")

SUPABASE_URL = os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
VERCEL_TOKEN = os.environ.get("VERCEL_TOKEN", "")
SITE_URL     = os.environ.get("NEXT_PUBLIC_SITE_URL", "https://mygoodpick.com")

# ── Merchants config ────────────────────────────────────────────────────────────────────────
# Les partenaires Awin ont leurs prix mis à jour via import-awin-feed.py,
# non par scraping. Ils sont exclus automatiquement de ce script.

_merchants_cfg_path = os.path.join(os.path.dirname(__file__), "..", "config", "merchants.json")
try:
    with open(_merchants_cfg_path, encoding="utf-8") as _f:
        _merchants_cfg = json.load(_f)
    AWIN_PARTNERS: frozenset[str] = frozenset(
        m["key"] for m in _merchants_cfg["merchants"] if m.get("network") == "awin"
    )
except FileNotFoundError:
    log.warning("config/merchants.json introuvable — aucun filtre Awin appliqué")
    AWIN_PARTNERS = frozenset()

# Proxy rotatifs (SOCKS5 ou HTTP) — format: "proto://user:pass@host:port"
PROXY_LIST: list[str] = [
    p.strip() for p in os.environ.get("SCRAPER_PROXY_LIST", "").split(",") if p.strip()
]

SCRAPINGBEE_KEY = os.environ.get("SCRAPINGBEE_API_KEY", "")

CONCURRENT_REQUESTS = int(os.environ.get("SCRAPER_CONCURRENCY", "5"))
DELAY_MIN  = 2.0   # secondes, délai minimum entre requêtes par domaine
DELAY_MAX  = 8.0
MAX_RETRIES = 3
TIMEOUT     = 20   # secondes

# ── Structures de données ─────────────────────────────────────────────────────

@dataclass
class ScrapeResult:
    partner:      str
    country:      str
    product_name: str
    url:          str
    price:        Optional[float]   = None
    currency:     str               = "EUR"
    in_stock:     bool              = True
    error:        Optional[str]     = None
    scraped_at:   str               = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class ScrapeTarget:
    product_id:    str
    comparison_id: str
    product_name:  str
    partner:       str
    country:       str
    current_url:   str
    link_id:       str

# ── User-Agents pool ──────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
]

def random_headers(referer: str = "") -> dict:
    return {
        "User-Agent":       random.choice(USER_AGENTS),
        "Accept":           "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language":  "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding":  "gzip, deflate, br",
        "Connection":       "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest":   "document",
        "Sec-Fetch-Mode":   "navigate",
        "Sec-Fetch-Site":   "none" if not referer else "same-origin",
        **({"Referer": referer} if referer else {}),
    }

# ── Adaptateurs de scraping par site ─────────────────────────────────────────

class BaseAdapter:
    """Classe parente pour tous les adaptateurs de sites marchands."""

    name:   str = ""
    domain: str = ""

    def build_search_url(self, product_name: str) -> str:
        raise NotImplementedError

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        """Retourne (prix, devise, en_stock)."""
        raise NotImplementedError

    def parse_search_results(self, html: str) -> list[dict]:
        """Retourne liste de {name, url, price, currency} depuis une page de résultats."""
        return []


class AmazonFRAdapter(BaseAdapter):
    name   = "amazon_fr"
    domain = "www.amazon.fr"

    AMAZON_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG_FR", "afprod-21")

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.amazon.fr/s?k={q}&tag={self.AMAZON_TAG}"

    def build_product_url(self, asin: str) -> str:
        return f"https://www.amazon.fr/dp/{asin}?tag={self.AMAZON_TAG}"

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        soup = BeautifulSoup(html, "lxml")

        # Détection anti-bot
        if "robot" in html.lower() and len(html) < 5000:
            raise BlockedError("Amazon robot check détecté")

        # Prix principal (page produit)
        price_el = (
            soup.select_one(".a-price .a-offscreen") or
            soup.select_one("#priceblock_ourprice") or
            soup.select_one("#priceblock_dealprice") or
            soup.select_one(".a-price-whole")
        )

        in_stock = True
        unavail  = soup.select_one("#availability .a-color-price")
        if unavail and "disponible" not in unavail.text.lower():
            in_stock = False

        if price_el:
            raw = price_el.get_text(strip=True).replace("\xa0", "").replace(",", ".").replace("€", "").replace("£", "").strip()
            raw = re.sub(r"[^\d.]", "", raw.split(".")[0] + "." + raw.split(".")[-1] if raw.count(".") > 1 else raw)
            try:
                return float(raw), "EUR", in_stock
            except ValueError:
                pass
        return None, "EUR", in_stock

    def parse_search_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for item in soup.select('[data-component-type="s-search-result"]')[:5]:
            title_el = item.select_one("h2 a span")
            price_el = item.select_one(".a-price .a-offscreen")
            link_el  = item.select_one("h2 a")
            asin     = item.get("data-asin", "")
            if not title_el or not asin:
                continue
            raw_price = price_el.get_text(strip=True) if price_el else ""
            try:
                price = float(re.sub(r"[^\d,]", "", raw_price).replace(",", "."))
            except Exception:
                price = None
            results.append({
                "name":  title_el.get_text(strip=True),
                "url":   self.build_product_url(asin),
                "price": price,
                "currency": "EUR",
                "asin":  asin,
            })
        return results


class AmazonDEAdapter(AmazonFRAdapter):
    name   = "amazon_de"
    domain = "www.amazon.de"
    AMAZON_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG_DE", "monsite-23")

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.amazon.de/s?k={q}&tag={self.AMAZON_TAG}"

    def build_product_url(self, asin: str) -> str:
        return f"https://www.amazon.de/dp/{asin}?tag={self.AMAZON_TAG}"


class AmazonUKAdapter(AmazonFRAdapter):
    name     = "amazon_uk"
    domain   = "www.amazon.co.uk"
    AMAZON_TAG = os.environ.get("AMAZON_ASSOCIATE_TAG_UK", "monsite-22")

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.amazon.co.uk/s?k={q}&tag={self.AMAZON_TAG}"

    def build_product_url(self, asin: str) -> str:
        return f"https://www.amazon.co.uk/dp/{asin}?tag={self.AMAZON_TAG}"

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        price, _, in_stock = super().parse_price(html, url)
        return price, "GBP", in_stock


class FnacAdapter(BaseAdapter):
    name   = "fnac"
    domain = "www.fnac.com"

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.fnac.com/SearchResult/ResultList.aspx?Search={q}&ref=aff_test"

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        soup = BeautifulSoup(html, "lxml")
        price_el = (
            soup.select_one(".f-priceBox-price") or
            soup.select_one('[itemprop="price"]') or
            soup.select_one(".userPrice span")
        )
        in_stock = soup.select_one(".f-availability--available") is not None

        if price_el:
            raw = re.sub(r"[^\d,]", "", price_el.get_text(strip=True)).replace(",", ".")
            try:
                return float(raw), "EUR", in_stock
            except ValueError:
                pass
        return None, "EUR", in_stock

    def parse_search_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for item in soup.select(".Article-itemWrapper")[:5]:
            title_el = item.select_one(".Article-desc")
            price_el = item.select_one(".f-priceBox-price")
            link_el  = item.select_one("a.Article-thumb") or item.select_one("a")
            if not title_el or not link_el:
                continue
            href = link_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.fnac.com" + href
            raw_price = price_el.get_text(strip=True) if price_el else ""
            try:
                price = float(re.sub(r"[^\d,]", "", raw_price).replace(",", "."))
            except Exception:
                price = None
            results.append({
                "name":     title_el.get_text(strip=True),
                "url":      href,
                "price":    price,
                "currency": "EUR",
            })
        return results


class CdiscountAdapter(BaseAdapter):
    name   = "cdiscount"
    domain = "www.cdiscount.com"

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.cdiscount.com/search/#f=1&keyword={q}"

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        soup = BeautifulSoup(html, "lxml")
        price_el = (
            soup.select_one(".fpPrice") or
            soup.select_one('[class*="price"]')
        )
        in_stock = soup.select_one('[class*="avail"]') is not None

        if price_el:
            raw = re.sub(r"[^\d,]", "", price_el.get_text(strip=True)).replace(",", ".")
            try:
                return float(raw), "EUR", in_stock
            except ValueError:
                pass
        return None, "EUR", in_stock

    def parse_search_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for item in soup.select(".prdtBlkLst_item, article.pdtCard")[:5]:
            title_el = item.select_one(".prdtBTit, .product-title")
            price_el = item.select_one(".fpPrice, .price")
            link_el  = item.select_one("a")
            if not title_el or not link_el:
                continue
            href = link_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.cdiscount.com" + href
            raw_price = price_el.get_text(strip=True) if price_el else ""
            try:
                price = float(re.sub(r"[^\d,]", "", raw_price).replace(",", "."))
            except Exception:
                price = None
            results.append({
                "name":     title_el.get_text(strip=True),
                "url":      href,
                "price":    price,
                "currency": "EUR",
            })
        return results


class DartyAdapter(BaseAdapter):
    name   = "darty"
    domain = "www.darty.com"

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.darty.com/nav/recherche?text={q}"

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        soup = BeautifulSoup(html, "lxml")
        price_el = (
            soup.select_one('[class*="price"]') or
            soup.select_one('[itemprop="price"]')
        )
        in_stock = "rupture" not in html.lower()

        if price_el:
            raw = re.sub(r"[^\d,]", "", price_el.get_text(strip=True)).replace(",", ".")
            try:
                return float(raw), "EUR", in_stock
            except ValueError:
                pass
        return None, "EUR", in_stock


class EbayFRAdapter(BaseAdapter):
    name   = "ebay_fr"
    domain = "www.ebay.fr"

    # eBay a une API publique de recherche REST — plus fiable que scraping HTML
    EBAY_APP_ID = os.environ.get("EBAY_APP_ID", "")

    def build_search_url(self, product_name: str) -> str:
        q = quote_plus(product_name)
        return f"https://www.ebay.fr/sch/i.html?_nkw={q}&_sop=12&LH_BIN=1"

    def parse_price(self, html: str, url: str) -> tuple[Optional[float], str, bool]:
        soup = BeautifulSoup(html, "lxml")
        price_el = soup.select_one(".s-item__price")
        in_stock = True

        if price_el:
            raw = re.sub(r"[^\d,]", "", price_el.get_text(strip=True).split("EUR")[-1]).replace(",", ".")
            try:
                return float(raw), "EUR", in_stock
            except ValueError:
                pass
        return None, "EUR", in_stock

    def parse_search_results(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        results = []
        for item in soup.select(".s-item")[:5]:
            title_el = item.select_one(".s-item__title")
            price_el = item.select_one(".s-item__price")
            link_el  = item.select_one("a.s-item__link")
            if not title_el or not link_el:
                continue
            if "Shop on eBay" in (title_el.text or ""):
                continue
            raw_price = price_el.get_text(strip=True) if price_el else ""
            try:
                price = float(re.sub(r"[^\d,]", "", raw_price.split("EUR")[-1]).replace(",", "."))
            except Exception:
                price = None
            results.append({
                "name":     title_el.get_text(strip=True),
                "url":      link_el.get("href", ""),
                "price":    price,
                "currency": "EUR",
            })
        return results


# Registre des adaptateurs
ADAPTERS: dict[str, BaseAdapter] = {
    "amazon_fr": AmazonFRAdapter(),
    "amazon_de": AmazonDEAdapter(),
    "amazon_uk": AmazonUKAdapter(),
    "fnac":      FnacAdapter(),
    "cdiscount": CdiscountAdapter(),
    "darty":     DartyAdapter(),
    "ebay_fr":   EbayFRAdapter(),
}

# ── Exceptions ────────────────────────────────────────────────────────────────

class BlockedError(Exception):
    """Le site a détecté et bloqué notre requête."""


# ── Client HTTP avec proxy + retry ────────────────────────────────────────────

_domain_last_request: dict[str, float] = {}

async def polite_delay(domain: str) -> None:
    """Respecte un délai minimum par domaine pour éviter le ban."""
    last = _domain_last_request.get(domain, 0)
    wait = random.uniform(DELAY_MIN, DELAY_MAX) - (time.monotonic() - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _domain_last_request[domain] = time.monotonic()


async def fetch_html(
    session:         aiohttp.ClientSession,
    url:             str,
    domain:          str,
    proxy:           Optional[str] = None,
    attempt:         int = 1,
) -> str:
    await polite_delay(domain)
    headers = random_headers(referer=f"https://{domain}/")

    try:
        async with session.get(
            url,
            headers=headers,
            proxy=proxy,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT),
            allow_redirects=True,
        ) as resp:
            if resp.status == 429:
                raise BlockedError(f"429 Too Many Requests sur {domain}")
            if resp.status == 503:
                raise BlockedError(f"503 Service Unavailable sur {domain}")
            if resp.status >= 400:
                raise aiohttp.ClientResponseError(resp.request_info, resp.history, status=resp.status)
            return await resp.text()

    except (BlockedError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        if attempt < MAX_RETRIES:
            backoff = 2 ** attempt + random.uniform(0, 2)
            log.warning(f"Tentative {attempt}/{MAX_RETRIES} échouée pour {url} ({exc}) — retry dans {backoff:.1f}s")
            await asyncio.sleep(backoff)
            new_proxy = random.choice(PROXY_LIST) if PROXY_LIST else None
            return await fetch_html(session, url, domain, proxy=new_proxy, attempt=attempt + 1)

        # Fallback ScrapingBee
        if SCRAPINGBEE_KEY:
            log.info(f"Fallback ScrapingBee pour {url}")
            return await fetch_via_scrapingbee(session, url)

        raise


async def fetch_via_scrapingbee(session: aiohttp.ClientSession, url: str) -> str:
    """Utilise ScrapingBee (API payante) en dernier recours."""
    params = {
        "api_key":        SCRAPINGBEE_KEY,
        "url":            url,
        "render_js":      "false",
        "premium_proxy":  "true",
        "country_code":   "fr",
    }
    api_url = "https://app.scrapingbee.com/api/v1/?" + urlencode(params)
    async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
        return await resp.text()


# ── Scraping d'un lien affilié existant ───────────────────────────────────────

async def scrape_link(
    session: aiohttp.ClientSession,
    target:  ScrapeTarget,
    sem:     asyncio.Semaphore,
    dry_run: bool = False,
) -> ScrapeResult:
    adapter = ADAPTERS.get(target.partner)
    if not adapter:
        return ScrapeResult(
            partner=target.partner, country=target.country,
            product_name=target.product_name, url=target.current_url,
            error=f"Pas d'adaptateur pour {target.partner}",
        )

    proxy = random.choice(PROXY_LIST) if PROXY_LIST else None

    async with sem:
        try:
            html = await fetch_html(session, target.current_url, adapter.domain, proxy=proxy)
            price, currency, in_stock = adapter.parse_price(html, target.current_url)

            result = ScrapeResult(
                partner=target.partner,
                country=target.country,
                product_name=target.product_name,
                url=target.current_url,
                price=price,
                currency=currency,
                in_stock=in_stock,
            )
            log.info(f"✅  {target.partner:<12} {target.product_name[:30]:<30} {price} {currency} (stock={in_stock})")
            return result

        except Exception as exc:
            log.error(f"❌  {target.partner:<12} {target.product_name[:30]:<30} ERREUR: {exc}")
            return ScrapeResult(
                partner=target.partner, country=target.country,
                product_name=target.product_name, url=target.current_url,
                error=str(exc),
            )


# ── Découverte de nouveaux produits (search scraping) ─────────────────────────

async def discover_products_for_category(
    session:       aiohttp.ClientSession,
    category_name: str,
    partners:      list[str],
    sem:           asyncio.Semaphore,
) -> list[dict]:
    """
    Scrape les pages de résultats de recherche pour trouver de nouveaux produits
    dans une catégorie donnée. Retourne une liste de candidats produits.
    """
    all_candidates = []

    for partner_name in partners:
        adapter = ADAPTERS.get(partner_name)
        if not adapter:
            continue

        search_url = adapter.build_search_url(category_name)
        proxy = random.choice(PROXY_LIST) if PROXY_LIST else None

        async with sem:
            try:
                html = await fetch_html(session, search_url, adapter.domain, proxy=proxy)
                candidates = adapter.parse_search_results(html)
                for c in candidates:
                    c["partner"]  = partner_name
                    c["source"]   = "search"
                    c["category"] = category_name
                all_candidates.extend(candidates)
                log.info(f"🔍  Découverte {partner_name}: {len(candidates)} candidats pour '{category_name}'")
            except Exception as exc:
                log.error(f"❌  Découverte {partner_name} '{category_name}': {exc}")

    # Dédoublonnage par nom normalisé
    seen = set()
    unique = []
    for c in all_candidates:
        key = re.sub(r"\W+", "", c["name"].lower())[:40]
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return unique


# ── Upsert Supabase ────────────────────────────────────────────────────────────

def update_supabase(results: list[ScrapeResult], link_map: dict[str, str], dry_run: bool) -> None:
    """Met à jour les prix dans Supabase."""
    if dry_run:
        log.info("DRY RUN — aucune écriture Supabase")
        return

    if not SUPABASE_URL or not SUPABASE_KEY:
        log.warning("Variables Supabase manquantes — skip écriture")
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    updated = skipped = errors = 0
    for result in results:
        if result.error:
            skipped += 1
            continue

        link_id = link_map.get(f"{result.partner}|{result.product_name}")
        if not link_id:
            skipped += 1
            continue

        payload = {
            "price":        result.price,
            "in_stock":     result.in_stock,
            "currency":     result.currency,
            "last_checked": result.scraped_at,
        }
        try:
            sb.table("affiliate_links").update(payload).eq("id", link_id).execute()
            updated += 1
        except Exception as exc:
            log.error(f"Supabase update failed for link {link_id}: {exc}")
            errors += 1

    log.info(f"Supabase : {updated} mis à jour, {skipped} ignorés, {errors} erreurs")


async def trigger_vercel_revalidation(comparison_slugs: list[str], locales: list[str] = ["fr", "en", "de"]) -> None:
    """Déclenche la revalidation ISR Vercel pour les pages mises à jour."""
    if not VERCEL_TOKEN:
        return

    revalidate_url = f"{SITE_URL}/api/revalidate"
    async with aiohttp.ClientSession() as session:
        for slug in comparison_slugs:
            for locale in locales:
                try:
                    async with session.post(
                        revalidate_url,
                        json={"slug": slug, "locale": locale},
                        headers={"Authorization": f"Bearer {VERCEL_TOKEN}"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        if resp.status == 200:
                            log.info(f"ISR revalidé: /{locale}/.../{slug}")
                except Exception as exc:
                    log.warning(f"ISR revalidation failed for {slug}: {exc}")


# ── Orchestration principale ──────────────────────────────────────────────────

async def run(partner_filter: Optional[str], dry_run: bool, discover: bool) -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1. Charger tous les liens affiliés depuis Supabase
    query = sb.table("affiliate_links").select("id, product_id, comparison_id, partner, country, url, price")
    if partner_filter:
        query = query.eq("partner", partner_filter)

    links_res  = query.execute()
    prod_res   = sb.table("products").select("id, name").execute()

    links    = links_res.data or []
    products = {p["id"]: p["name"] for p in (prod_res.data or [])}

    # Exclure les partenaires Awin (leurs prix viennent du feed, pas du scraping)
    awin_skipped = [l for l in links if l["partner"] in AWIN_PARTNERS]
    links = [l for l in links if l["partner"] not in AWIN_PARTNERS]
    if awin_skipped:
        log.info(f"⏩  {len(awin_skipped)} liens Awin exclus du scraping — mis à jour via import-awin-feed.py")

    log.info(f"📦  {len(links)} liens à scraper")

    # Map (partner|product_name) -> link_id pour upsert
    link_map: dict[str, str] = {}
    targets:  list[ScrapeTarget] = []

    for link in links:
        prod_name = products.get(link["product_id"], "")
        link_map[f"{link['partner']}|{prod_name}"] = link["id"]
        targets.append(ScrapeTarget(
            product_id=link["product_id"],
            comparison_id=link.get("comparison_id", ""),
            product_name=prod_name,
            partner=link["partner"],
            country=link["country"],
            current_url=link["url"],
            link_id=link["id"],
        ))

    # 2. Découverte de nouveaux produits (optionnel)
    new_candidates: list[dict] = []
    if discover:
        cat_res = sb.table("categories").select("name_fr, slug").eq("is_active", True).execute()
        categories = cat_res.data or []
        partners_to_discover = list(ADAPTERS.keys())

        connector = aiohttp.TCPConnector(limit=CONCURRENT_REQUESTS)
        sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [
                discover_products_for_category(session, cat["name_fr"], partners_to_discover, sem)
                for cat in categories
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, list):
                    new_candidates.extend(r)

        if new_candidates:
            output_path = os.path.join(os.path.dirname(__file__), "..", "data", "discovered_products.json")
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(new_candidates, f, ensure_ascii=False, indent=2)
            log.info(f"💡  {len(new_candidates)} nouveaux candidats enregistrés dans data/discovered_products.json")

    # 3. Scraping prix en parallèle
    sem = asyncio.Semaphore(CONCURRENT_REQUESTS)
    connector = aiohttp.TCPConnector(limit=CONCURRENT_REQUESTS + 2)

    async with aiohttp.ClientSession(connector=connector) as session:
        tasks  = [scrape_link(session, t, sem, dry_run) for t in targets]
        results: list[ScrapeResult] = await asyncio.gather(*tasks, return_exceptions=False)

    # 4. Statistiques
    success  = sum(1 for r in results if r.price is not None)
    failed   = sum(1 for r in results if r.error)
    no_price = sum(1 for r in results if r.price is None and not r.error)

    log.info(f"\n📊  Résultats : {success} prix trouvés | {no_price} sans prix | {failed} erreurs")

    # 5. Écriture Supabase
    update_supabase(results, link_map, dry_run)

    # 6. Revalidation ISR pour les comparaisons affectées
    affected_comp_ids = {t.comparison_id for t, r in zip(targets, results) if r.price is not None and t.comparison_id}
    if affected_comp_ids and not dry_run:
        comp_res = sb.table("comparisons").select("slug").in_("id", list(affected_comp_ids)).execute()
        slugs    = [c["slug"] for c in (comp_res.data or [])]
        await trigger_vercel_revalidation(slugs)

    # 7. Sauvegarde rapport JSON
    report = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total":      len(results),
        "success":    success,
        "failed":     failed,
        "results":    [
            {"partner": r.partner, "product": r.product_name, "price": r.price,
             "currency": r.currency, "in_stock": r.in_stock, "error": r.error}
            for r in results
        ],
    }
    report_path = os.path.join(os.path.dirname(__file__), "..", "data", "scrape_report.json")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info(f"📄  Rapport enregistré dans data/scrape_report.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper de prix affiliés AffiliCompare")
    parser.add_argument("--partner",   help="Filtrer sur un partenaire (ex: amazon_fr)")
    parser.add_argument("--dry-run",   action="store_true", help="Ne pas écrire dans Supabase")
    parser.add_argument("--discover",  action="store_true", help="Découvrir de nouveaux produits via search")
    args = parser.parse_args()

    asyncio.run(run(args.partner, args.dry_run, args.discover))


if __name__ == "__main__":
    main()
