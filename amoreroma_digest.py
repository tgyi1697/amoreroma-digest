#!/usr/bin/env python3
"""
Róma-témájú napi hír-digest (amoreroma.hu)
=============================================
Források: orf.at, derstandard.at, euronews.com, travelbook.de,
          traveltomorrow.com, siviaggia.it, bbc.com/travel, wantedinrome.com
          (ugyanaz a 8 forrás, mint a tourism_digest.py / vizpartok_digest.py-
          nál), PLUSZ ÚJ: reuters.com és romatoday.it (lásd lent, technikai
          megjegyzések).

Ez a script a vizpartok_digest.py (KÉSZ, ÉLESBEN MŰKÖDŐ) mintáját követi
1:1 arányban, Róma-témára szabva:

1. A válogatás (select_and_rank) Claude-promptja KIFEJEZETTEN RÓMA-témájú
   relevanciát követel meg: ókori Róma, Róma város, műemlékek, római
   esküvő/romantika, Vatikán (VILÁGI/kulturális szemszögből, VAGY nagy
   nyilvános misék/pápai hírek - de a Vatikán belső egyházpolitikai ügyei
   KIZÁRVA), Róma környéke (Lazio).
2. Az összefoglalás (summarize_article) egy RÓMA-FÓKUSZÚ promptot kap,
   ugyanazzal az elvvel, mint a vizpartok.hu-nál: ha a forráscikk egy
   általánosabb listás cikk, csak a Róma-részre koncentrálunk.
3. A kész magyar összefoglalón lefuttatjuk a roma_keyword_scorer.py-t
   minőségbiztosítási/bizalmi jelzőként (nem dönt a be/ki-kerülésről).
4. A WordPress-feltöltés az amoreroma.hu SIMA "post" post type-jára megy.
   FONTOS(!): az amoreroma.hu WP-struktúrája MÉG NINCS FELTÉRKÉPEZVE - ezért
   egyelőre a vizpartok.hu-nál bevált, ACF NÉLKÜLI mintát követjük. Ha
   István elküldi a tényleges oldalstruktúrát, a wp_create_draft()-ot
   érdemes lesz felülvizsgálni.

ÚJ a vizpartok_digest.py-hoz képest (közös kérés mindkét új digesthez):
- Mivel az amoreroma.hu-n JELENLEG NINCSENEK ACF mezők, a képek forrását
  NEM egy ACF mezőbe írjuk, hanem a cikk törzsének VÉGÉRE, egy "Képek
  forrása: ..." szövegű bekezdésbe (lásd render_content_html()).
- A szövegben a forrásra való hivatkozást (pl. "A wantedinrome.com cikke
  szerint...") automatikusan LINKKEL látjuk el, ami a forrás FŐOLDALÁRA
  mutat (nem a konkrét cikkre) - lásd linkify_source_mention() és
  SOURCE_HOMEPAGES.

TECHNIKAI MEGJEGYZÉSEK AZ ÚJ FORRÁSOKRÓL:
- reuters.com: a Reuters 2020 óta NEM ad ki saját, közvetlen RSS-feedet.
  Emiatt egy Google News-alapú proxy-feedet használunk (site:reuters.com
  szűréssel, Róma-témájú kulcsszavakkal szűkítve) - ez működik, de a linkek
  Google News-átirányításon mennek keresztül, ami néha nem enged teljes
  cikkszöveget letölteni. A meglévő "ha nincs elég tartalom, a cikk
  kimarad" védőháló ezt kezeli.
- romatoday.it: a feed URL-je (RSS_FEEDS lent) a Citynews-hálózat többi
  oldalán (pl. milanotoday.it/rss) látott minta alapján lett összeállítva,
  DE MÉG NEM LETT ÉLESBEN LEELLENŐRIZVE - érdemes az első futás logját
  megnézni, hogy tényleg érvényes XML-t ad-e vissza. A romatoday.it egy
  ÁLTALÁNOS helyi hírportál (bűnügy, közlekedés, önkormányzati hírek is
  benne vannak) - ezért KEYWORD_FILTERED_SOURCES-ként, szigorú
  kulcsszó-előszűréssel kezeljük, NEM PURE_TRAVEL_SOURCES-ként.

A Facebook-posztolás NEM ennek a scriptnek a feladata (egyelőre nem is
kérték, csak később, opcionálisan).

Beállítás: lásd README.md.
"""

import os
import re
import json
import time
import base64
import smtplib
import mimetypes
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import urljoin, quote

import feedparser
import requests
from bs4 import BeautifulSoup
import anthropic

from roma_keyword_scorer import score_article

# ---------------------------------------------------------------------------
# BEÁLLÍTÁSOK
# ---------------------------------------------------------------------------

MAX_AGE_HOURS = 24
# A felhasználó kérésére 4-re emelve (a vizpartok.hu-nál bevált 2-höz
# képest) - Róma egy jóval szűkebb, specifikusabb téma, mint "vízpart"
# általában, ezért a 4 "tiszta" utazási portál (travelbook.de,
# traveltomorrow.com, siviaggia.it, bbc.com/travel) egyenként ritkábban
# hoz Róma-releváns cikket - a magasabb limit nagyobb mozgásteret ad
# ezeknek a forrásoknak, amikor mégis van jó találatuk.
PURE_SOURCE_DAILY_LIMIT = 4

# A felhasználó kérése szerint napi 6 hír a cél
DAILY_TOTAL_LIMIT = 6
PROCESSING_BUFFER = 10

MODEL = "claude-sonnet-4-6"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AmoreRomaDigestBot/1.0; +personal use)"
}

WP_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
}

ARTICLE_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8,hu;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

ARTICLE_SESSION = requests.Session()
ARTICLE_SESSION.headers.update(ARTICLE_FETCH_HEADERS)

# A Reuters-hez Google News proxy-feedet használunk (lásd fenti technikai
# megjegyzés a docstringben) - Róma-témájú kulcsszavakkal szűkítve.
_REUTERS_QUERY = (
    'site:reuters.com (Rome OR Vatican OR Colosseum OR "ancient Rome" '
    'OR Lazio OR Pantheon)'
)
REUTERS_FEED_URL = (
    f"https://news.google.com/rss/search?q={quote(_REUTERS_QUERY)}"
    f"&hl=en-US&gl=US&ceid=US:en"
)

RSS_FEEDS = {
    "orf.at": [
        "https://rss.orf.at/news.xml",
        "https://rss.orf.at/vorarlberg.xml",
        "https://rss.orf.at/tirol.xml",
        "https://rss.orf.at/salzburg.xml",
        "https://rss.orf.at/kaernten.xml",
        "https://rss.orf.at/steiermark.xml",
        "https://rss.orf.at/ooe.xml",
        "https://rss.orf.at/noe.xml",
        "https://rss.orf.at/wien.xml",
        "https://rss.orf.at/burgenland.xml",
    ],
    "derstandard.at": [
        "https://www.derstandard.at/rss/lifestyle",
        "https://www.derstandard.at/rss/wirtschaft",
    ],
    "euronews.com": [
        "https://www.euronews.com/rss",
    ],
    "travelbook.de": [
        "https://www.travelbook.de/feed",
    ],
    "traveltomorrow.com": [
        "https://traveltomorrow.com/feed/",
    ],
    "siviaggia.it": [
        "https://siviaggia.it/feed/",
    ],
    "bbc.com/travel": [
        "https://www.bbc.com/travel/feed.rss",
    ],
    "wantedinrome.com": [
        "https://www.wantedinrome.com/news?format=rss",
    ],
    "reuters.com": [
        REUTERS_FEED_URL,
    ],
    "romatoday.it": [
        # MÉG NEM ELLENŐRIZVE ÉLESBEN - lásd a technikai megjegyzést fent.
        "https://www.romatoday.it/rss/",
    ],
}

# A forrás FŐOLDALÁRA mutató URL-ek - ide linkeljük a szövegben lévő
# forrásra való hivatkozást (lásd linkify_source_mention()).
SOURCE_HOMEPAGES = {
    "orf.at": "https://www.orf.at/",
    "derstandard.at": "https://www.derstandard.at/",
    "euronews.com": "https://www.euronews.com/",
    "travelbook.de": "https://www.travelbook.de/",
    "traveltomorrow.com": "https://traveltomorrow.com/",
    "siviaggia.it": "https://siviaggia.it/",
    "bbc.com/travel": "https://www.bbc.com/travel",
    "wantedinrome.com": "https://www.wantedinrome.com/",
    "reuters.com": "https://www.reuters.com/",
    "romatoday.it": "https://www.romatoday.it/",
}

KEYWORD_FILTERED_SOURCES = {
    "orf.at", "derstandard.at", "euronews.com", "wantedinrome.com",
    "reuters.com", "romatoday.it",
}
PURE_TRAVEL_SOURCES = {"travelbook.de", "traveltomorrow.com", "siviaggia.it", "bbc.com/travel"}

# FONTOS: ez a KEYWORD_FILTERED_SOURCES-hez tartozó ELŐSZŰRŐ, NEM a végső
# Róma-relevancia döntés (azt a select_and_rank() Claude-hívása dönti el).
# Különösen a romatoday.it-nél kritikus, mert az egy ÁLTALÁNOS helyi
# hírportál (bűnügy, közlekedés, önkormányzat is benne van) - enélkül a
# válogatás rengeteg irreleváns jelöltet kapna.
KEYWORDS = [
    "tourism", "tourismus", "touris",
    "reise", "reisen", "urlaub", "urlauber",
    "hotel", "destination", "sightseeing", "excursion",
    "travel", "traveler", "traveller", "vacation", "holiday", "holidays",
    "trip", "ferien", "route", "geheimtipp",
    # Kifejezetten Róma-témájú kulcsszavak (magyar átirat nélkül, a
    # forrásnyelveken: német/angol/olasz)
    "rom", "rome", "roma", "vatikan", "vatican", "vaticano",
    "kolosseum", "colosseum", "colosseo", "papst", "pope", "papa",
    "pantheon", "forum romanum", "palatin", "palatino", "trastevere",
    "lazio", "hochzeit", "wedding", "matrimonio", "sposi", "nozze",
    "museum", "museo", "monument", "monumento", "unesco",
    "archaeology", "archäologie", "archeologia", "scavo", "scavi",
    "basilica", "kirche", "church", "chiesa", "sehenswürdigkeit",
    "entry fee", "tourist tax",
]

PATH_FILTER_SOURCES = {"euronews.com": "/travel/"}

EXCLUDE_KEYWORDS = [
    "schneehöhe", "schneehöhen", "schneelage", "aktuelle schneehöhen",
    "stau an der grenze", "verkehrsmeldung",
    "urteil", "gericht", "klage", "versicherung",
    "deal", "angebot", "rabatt", "gutschein", "sale", "% off",
    "quiz", "gewinnspiel", "preisrätsel",
    "opinion", "kolumne", "kommentar:",
    "offerta", "sconto", "codice sconto", "black friday",
    "oroscopo", "sondaggio",
]

FREE_LICENSE_KEYWORDS = [
    "wikimedia commons", "gemeinfrei", "public domain", "creative commons",
    "cc by", "cc0", "pixabay", "unsplash", "gnu free documentation",
]

OPENVERSE_ALLOWED_LICENSES = "cc0,pdm,by,by-sa"
OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"

MAX_ARTICLE_CHARS = 6000


# ---------------------------------------------------------------------------
# 1. RSS BEGYŰJTÉS (azonos logika, mint a vizpartok_digest.py-nál)
# ---------------------------------------------------------------------------

def collect_candidates():
    candidates = []
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=MAX_AGE_HOURS)

    # Diagnosztikai számlálók forrásonként - ez segít eldönteni egy üres/
    # gyenge napnál, hogy egy adott forrás (pl. romatoday.it, reuters.com)
    # EGYÁLTALÁN ad-e vissza nyers RSS-bejegyzést, és ebből hány jut át az
    # előszűrésen (24 órás korhatár + kulcsszó/kizáró-lista) - enélkül a
    # végső "Talált (előszűrt) jelölt: N" összesített szám nem árulja el,
    # melyik forrás hibádzik vagy melyiknél túl szigorú/laza a szűrés.
    source_stats = {name: {"raw": 0, "after_filter": 0, "http_error": False} for name in RSS_FEEDS}

    for source_name, urls in RSS_FEEDS.items():
        for feed_url in urls:
            try:
                parsed = feedparser.parse(feed_url)
            except Exception as e:
                print(f"  Hiba a feed beolvasásakor ({source_name}, {feed_url}): {e}")
                source_stats[source_name]["http_error"] = True
                continue

            # A feedparser HTTP-hibánál (pl. 403/404) NEM mindig dob
            # kivételt - a `status` mezőben jelenik meg, ha van. Ezt is
            # jelezzük, mert pontosan ez a romatoday.it-nél/reuters.com-nál
            # várható hibamód (bot-blokkolás, hibás URL stb.).
            http_status = getattr(parsed, "status", None)
            if http_status and http_status >= 400:
                print(f"  Figyelmeztetés: {source_name} ({feed_url}) HTTP {http_status} "
                      f"választ adott - a feed valószínűleg nem érhető el (blokkolás/hibás URL).")
                source_stats[source_name]["http_error"] = True

            source_stats[source_name]["raw"] += len(parsed.entries)

            for entry in parsed.entries:
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                link = entry.get("link", "")

                rss_full_content = ""
                if entry.get("content"):
                    rss_full_content = entry["content"][0].get("value", "")

                if entry.get("published_parsed"):
                    published = datetime(*entry.published_parsed[:6])
                    if published < cutoff:
                        continue
                else:
                    published = None

                haystack = f"{title} {summary}".lower()

                if source_name in PURE_TRAVEL_SOURCES:
                    if any(kw in haystack for kw in EXCLUDE_KEYWORDS):
                        continue
                    include = True
                elif source_name in KEYWORD_FILTERED_SOURCES:
                    keyword_match = any(kw in haystack for kw in KEYWORDS)
                    path_needle = PATH_FILTER_SOURCES.get(source_name)
                    path_match = bool(path_needle) and path_needle in link
                    include = keyword_match or path_match
                else:
                    include = True

                if include:
                    candidates.append({
                        "source": source_name,
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "published": published,
                        "rss_full_content": rss_full_content,
                    })
                    source_stats[source_name]["after_filter"] += 1

    seen = set()
    unique = []
    for c in candidates:
        if c["link"] not in seen:
            seen.add(c["link"])
            unique.append(c)

    print("Forrásonkénti bontás (nyers RSS-bejegyzés / előszűrésen átjutott):")
    for name, stats in source_stats.items():
        flag = " [HIBA/BLOKKOLÁS GYANÚJA]" if stats["http_error"] else ""
        print(f"  {name}: {stats['raw']} / {stats['after_filter']}{flag}")

    return unique


# ---------------------------------------------------------------------------
# 2. AI-VÁLOGATÁS - RÓMA-TÉMÁJÚ RELEVANCIA-KÖVETELMÉNNYEL
# ---------------------------------------------------------------------------

AMOREROMA_SELECTION_SYSTEM_PROMPT = """Turisztikai/kulturális hírszerkesztő \
vagy az amoreroma.hu magyar, KIZÁRÓLAG RÓMÁVAL foglalkozó magazin számára. \
Egy JSON tömböt kapsz jelölt cikkekkel (index, forrás, cím, rövid leírás, \
megjelenés dátuma - NÉMET, ANGOL vagy OLASZ nyelvűek lehetnek). A feladatod, \
hogy kiválaszd és rangsorold a legjobbakat az alábbi szabályok szerint:

1. RÓMA-RELEVANCIA (LEGFONTOSABB SZŰRŐ): a cikknek TÉNYLEGESEN kapcsolódnia \
kell Rómához vagy Róma közvetlen környékéhez (Lazio régió): ókori Róma \
(régészet, romok, leletek, rekonstrukciók), Róma városa (események, \
fesztiválok, negyedek, gasztronómia, közlekedés/turisztikai fejlesztések), \
műemlékek (templomok, paloták, terek, szökőkutak, felújítások, \
jegyárak/nyitvatartás-változások), esküvő/romantika Rómában, kirándulóhelyek \
Róma környékén (pl. Tivoli, Ostia Antica, Frascati). A VATIKÁN mehet, HA \
világi/kulturális/művészeti szemszögből közelíti meg a témát (pl. Szent \
Péter-bazilika, Vatikáni Múzeumok, egy kiállítás), VAGY ha nagy, nyilvános \
misékről/eseményekről, illetve magáról a pápáról mint közszereplőről szól. \
A Vatikán BELSŐ EGYHÁZPOLITIKAI ügyei (pl. Kúria-viták, kánonjogi \
kérdések, egyházi kinevezések belpolitikája) NEM valók a digestbe - ez nem \
turisztikai/kulturális téma.

2. HELYI ZAJ KIZÁRVA: mivel az egyik forrás (romatoday.it) egy általános \
helyi hírportál, KIFEJEZETTEN dobd el a pusztán helyi közéleti/bűnügyi/\
közlekedési/önkormányzati híreket, amiknek NINCS turisztikai vagy \
kulturális relevanciája (pl. egy útfelújítás híre, egy helyi bűneset, egy \
önkormányzati közbeszerzés) - még akkor is, ha Rómában történtek.

3. DUPLIKÁTUM-ÖSSZEVONÁS: ha több cikk ugyanarról a konkrét eseményről \
szól, csak a legjobb/legrészletesebb EGYET tartsd meg.

4. PORTÁLONKÉNTI LIMIT: az alábbi négy forrásból ("travelbook.de", \
"traveltomorrow.com", "siviaggia.it", "bbc.com/travel") forrásonként \
MAXIMUM {pure_limit} cikket válassz ki összesen. A többi forrásra nincs \
ilyen limit.

5. MINŐSÉG: részesítsd előnyben az egyedi, látványos, kulturálisan vagy \
romantikusan érdekes cikkeket. Kerüld a száraz, tisztán közigazgatási-\
statisztikai jelentéseket, ha van helyettük érdekesebb alternatíva.

POLITIKAI/KATONAI KONFLIKTUS KIZÁRVA: SOHA ne válassz olyan cikket, \
aminek fő témája olasz belpolitika, politikai vagy katonai konfliktus - \
KIVÉVE, ha közvetlen, gyakorlati turisztikai/kulturális hatása van (pl. \
egy sztrájk miatt zárva tart egy múzeum).

6. VÉGSŐ LIMIT: a fentiek után válaszd ki és rangsorold (legjobb elöl) \
összesen MAXIMUM {total_limit} cikket. Ha egyetlen jelölt sem felel meg a \
Róma-relevancia-követelménynek, adj vissza egy ÜRES JSON tömböt ([]) - \
jobb egy üres nap, mint egy erőltetett, irreleváns válogatás.

VÁLASZ FORMÁTUMA: KIZÁRÓLAG egy JSON tömböt adj vissza a kiválasztott \
cikkek eredeti "index" mezőjével, rangsorolva (legjobb elöl). Semmi mást \
ne írj a JSON tömbön kívül.
Példa: [4, 12, 0, 7]"""


def select_and_rank(candidates):
    if not candidates:
        return []

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    slim = []
    for i, c in enumerate(candidates):
        slim.append({
            "index": i,
            "source": c["source"],
            "title": c["title"],
            "summary": (c["summary"] or "")[:300],
            "published": c["published"].isoformat() if c["published"] else None,
        })

    system_prompt = AMOREROMA_SELECTION_SYSTEM_PROMPT.format(
        pure_limit=PURE_SOURCE_DAILY_LIMIT,
        total_limit=DAILY_TOTAL_LIMIT + PROCESSING_BUFFER,
    )

    user_prompt = "Jelölt cikkek:\n" + json.dumps(slim, ensure_ascii=False, indent=2)

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = "".join(b.text for b in response.content if b.type == "text").strip()
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        indices = json.loads(raw)
        selected = [candidates[i] for i in indices if isinstance(i, int) and 0 <= i < len(candidates)]
        return selected
    except Exception as e:
        print(f"  Hiba a válogatás során: {e}")
        # Ugyanaz az elv, mint a vizpartok_digest.py-nál: a Róma-relevancia
        # eldöntése kifejezetten Claude-ítéletet igényel, ezért hiba esetén
        # üres listát adunk vissza.
        return []


# ---------------------------------------------------------------------------
# 3. CIKKSZÖVEG + SZABADON FELHASZNÁLHATÓ KÉP LETÖLTÉSE
#    (azonos logika, mint a vizpartok_digest.py-nál)
# ---------------------------------------------------------------------------

def _is_free_caption(text):
    t = text.lower()
    return any(kw in t for kw in FREE_LICENSE_KEYWORDS)


def _resolve_image_src(img_tag, base_url):
    src = img_tag.get("src") or img_tag.get("data-src")
    if not src:
        return None
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return urljoin(base_url, src)
    return src


def _extract_credit(caption):
    lower = caption.lower()
    idx = lower.find("foto:")
    if idx == -1:
        return caption
    return "Fotó:" + caption[idx + len("foto:"):].strip()


def find_free_image(soup, base_url):
    for fig in soup.find_all("figure"):
        img = fig.find("img")
        caption_el = fig.find("figcaption")
        caption = caption_el.get_text(" ", strip=True) if caption_el else ""
        if img and caption and _is_free_caption(caption):
            src = _resolve_image_src(img, base_url)
            if src:
                return src, _extract_credit(caption)

    for em in soup.find_all(["em", "i"]):
        text = em.get_text(" ", strip=True)
        if "foto:" in text.lower() and _is_free_caption(text):
            img = em.find_previous("img")
            if img:
                src = _resolve_image_src(img, base_url)
                if src:
                    return src, _extract_credit(text)

    return None, None


def fetch_article_content(url, rss_fallback_html=""):
    html_for_image_search = ""
    text = ""
    fetch_error = None

    try:
        resp = ARTICLE_SESSION.get(url, timeout=15)
        resp.raise_for_status()
        html_for_image_search = resp.text
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = soup.find_all("p")
        text = "\n".join(p.get_text(" ", strip=True) for p in paragraphs)
        text = re.sub(r"\n{2,}", "\n", text).strip()
    except Exception as e:
        fetch_error = str(e)

    MIN_USABLE_CHARS = 200
    if rss_fallback_html and len(text) < MIN_USABLE_CHARS:
        fallback_soup = BeautifulSoup(rss_fallback_html, "html.parser")
        fallback_paragraphs = fallback_soup.find_all("p")
        if fallback_paragraphs:
            fallback_text = "\n".join(
                p.get_text(" ", strip=True) for p in fallback_paragraphs
            )
        else:
            fallback_text = fallback_soup.get_text(" ", strip=True)
        fallback_text = re.sub(r"\n{2,}", "\n", fallback_text).strip()

        if len(fallback_text) > len(text):
            text = fallback_text
            if not html_for_image_search:
                html_for_image_search = rss_fallback_html

    if not text:
        if fetch_error:
            text = f"[Nem sikerült letölteni: {fetch_error}]"
        else:
            text = "[Nem található kinyerhető szöveg.]"
    text = text[:MAX_ARTICLE_CHARS]

    image_url, image_credit = (None, None)
    if html_for_image_search:
        image_soup = BeautifulSoup(html_for_image_search, "html.parser")
        image_url, image_credit = find_free_image(image_soup, url)

    return {"text": text, "image_url": image_url, "image_credit": image_credit}


def search_openverse_image(query):
    if not query:
        return None

    try:
        resp = requests.get(
            OPENVERSE_API_URL,
            params={
                "q": query,
                "license": OPENVERSE_ALLOWED_LICENSES,
                "page_size": 5,
            },
            headers=HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as e:
        print(f"    Openverse keresési hiba ('{query}'): {e}")
        return None

    for result in results:
        image_url = result.get("url")
        if not image_url:
            continue
        creator = result.get("creator") or "ismeretlen szerző"
        license_name = (result.get("license") or "").upper()
        license_version = result.get("license_version") or ""
        license_full = f"{license_name} {license_version}".strip()
        credit = f"{creator} / {license_full} (Openverse)"
        location = result.get("title") or query
        return {
            "image_url": image_url,
            "image_credit": credit,
            "image_location": location,
        }

    return None


# ---------------------------------------------------------------------------
# 4. STRUKTURÁLT (JSON) ÖSSZEFOGLALÁS - RÓMA-FÓKUSSZAL
# ---------------------------------------------------------------------------

AMOREROMA_SUMMARY_SYSTEM_PROMPT = """Turisztikai/kulturális hírszerkesztő \
vagy az amoreroma.hu magyar, KIZÁRÓLAG RÓMÁVAL foglalkozó magazin számára, \
amely 10 forrásból (orf.at, derstandard.at - német; euronews.com, \
bbc.com/travel, traveltomorrow.com, wantedinrome.com, reuters.com, \
romatoday.it - angol/olasz vegyesen; travelbook.de - német; siviaggia.it - \
olasz) dolgozik. A bemeneti cikkszöveg német, angol vagy olasz nyelvű \
lehet - magyarra fordítva, saját szavaiddal összefoglalva dolgozz.

KRITIKUS: RÓMA-FÓKUSZ, NEM TELJES ÁTFOGALMAZÁS. Ha a forráscikk egy \
általánosabb témájú (pl. "Olaszország 10 legszebb városa" listás cikk, \
aminek csak egy pontja Róma), az összefoglalódnak NE a teljes cikket \
kelljen lefednie - koncentrálj KIFEJEZETTEN a Rómával kapcsolatos részre.

VATIKÁN KEZELÉSE: ha a cikk a Vatikánról szól, KIZÁRÓLAG a világi/\
kulturális/turisztikai vonatkozásra (múzeumok, bazilika, művészet, nagy \
nyilvános misék/események, a pápa mint közszereplő) fókuszálj - a belső \
egyházpolitikai részleteket (kinevezések, kánonjogi viták) hagyd ki, még \
ha a forráscikk érinti is őket.

STÍLUS: magazinos, közérthető, olvasmányos, sztorizó megfogalmazás - de \
mindig a tényeken belül maradva. Kerüld a száraz, hivatalos stílust.

MAGÁZÁS, NE TEGEZÉS: mindig magázó formában szólítsd meg az olvasót.

HOSSZ: írj 4-6 bekezdést, összesen kb. 300-450 szó terjedelemben.

FORRÁSMEGJELÖLÉS A SZÖVEGBEN - KRITIKUS SZABÁLY: a cikk elején vagy \
második bekezdésében természetes módon utalj a forrásra, ÉS ehhez PONTOSAN \
a következő szöveget használd szó szerint, változtatás nélkül: \
"{source_name}" (pl. "A(z) {source_name} beszámolója szerint..." vagy "A(z) \
{source_name} cikke szerint..."). Ez azért kritikusan fontos, mert a \
rendszer ez alapján a PONTOS szöveg alapján fogja automatikusan linkkel \
ellátni a forrás nevét a cikk publikálásakor - ha átírod vagy más \
elnevezést használsz, a linkelés nem fog működni.

KRITIKUS SZABÁLY - HIÁNYOS TARTALOM: ha a letöltött cikkszöveg + az \
RSS-leírás együtt sem elég egy értelmes, tényszerű összefoglalóhoz, VAGY \
ha a cikk Róma-tartalma túl kevés/felszínes ahhoz, hogy önálló cikket \
lehessen belőle írni, állítsd az "usable" mezőt false-ra, és a többi \
mezőt hagyd üresen. Ha van elég Róma-tartalom, "usable": true.

SZERZŐI JOG: SOHA ne idézz szó szerint 15 szónál hosszabban.

A submit_summary eszközzel add át az elkészült összefoglalót. Ha nem \
kaptál szabadon felhasználható kép adatot, az image_url/image_credit/ \
image_location mezőket hagyd üresen - SOHA ne találj ki képet. Ilyenkor \
mindig adj meg egy image_search_query-t (lehetőleg a konkrét Róma-i \
helyszínre vonatkozót, pl. "Trevi fountain Rome" ne csak "Italy")."""

SUMMARY_TOOL = {
    "name": "submit_summary",
    "description": "Az elkészült magyar nyelvű, Róma-fókuszú cikk-összefoglaló beküldése.",
    "input_schema": {
        "type": "object",
        "properties": {
            "usable": {
                "type": "boolean",
                "description": "Volt-e elég RÓMA-témájú tartalom egy értelmes, önálló cikkhez.",
            },
            "title": {"type": "string", "description": "Magyar, figyelemfelkeltő cím."},
            "lead": {"type": "string", "description": "1-2 mondatos lead."},
            "paragraphs": {
                "type": "string",
                "description": (
                    "A cikk törzse, 4-6 bekezdés EGYETLEN string-ben, "
                    "a bekezdéseket két egymást követő sortöréssel "
                    "(\\n\\n) elválasztva - VALÓDI PRÓZA, nem JSON-tömb!"
                ),
            },
            "image_url": {"type": ["string", "null"]},
            "image_credit": {"type": ["string", "null"]},
            "image_location": {"type": ["string", "null"]},
            "image_search_query": {
                "type": ["string", "null"],
                "description": "1-3 szavas angol keresőkifejezés a konkrét Róma-i helyszínhez.",
            },
            "source_name": {"type": "string"},
            "published_date": {"type": ["string", "null"], "description": "ÉÉÉÉ-HH-NN"},
            "district": {
                "type": ["string", "null"],
                "description": "A cikkben érintett Róma-i negyed/környék magyar vagy olasz neve, ha releváns (pl. 'Trastevere').",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-3 releváns magyar kulcsszó kisbetűvel.",
            },
        },
        "required": ["usable", "paragraphs", "tags"],
    },
}


def _ensure_string_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        return [value] if value else []
    return []


def summarize_article(article, article_content):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    published_str = (
        article["published"].strftime("%Y-%m-%d")
        if article["published"] else None
    )

    if article_content["image_url"]:
        image_block = (
            f"Szabadon felhasználható kép:\n"
            f"URL: {article_content['image_url']}\n"
            f"Hitelesítés: {article_content['image_credit']}"
        )
    else:
        image_block = "Szabadon felhasználható kép: nincs"

    user_prompt = f"""Forrás: {article['source']}
Eredeti cím: {article['title']}
Megjelenés: {published_str or "ismeretlen"}
URL: {article['link']}

RSS-leírás:
{article['summary']}

Letöltött cikkszöveg (részleges lehet):
{article_content['text']}

{image_block}

Készítsd el a RÓMA-FÓKUSZÚ összefoglalót a submit_summary eszközzel. Ne \
felejtsd: a forrásra hivatkozáskor PONTOSAN a "{article['source']}" \
szöveget használd."""

    system_prompt = AMOREROMA_SUMMARY_SYSTEM_PROMPT.format(source_name=article["source"])

    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[SUMMARY_TOOL],
        tool_choice={"type": "tool", "name": "submit_summary"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_use_block = next(
        (b for b in response.content if b.type == "tool_use"), None
    )
    if tool_use_block is None:
        raise ValueError("A Claude válasza nem tartalmazott tool_use blokkot.")

    data = tool_use_block.input

    raw_paragraphs = data.get("paragraphs")
    if isinstance(raw_paragraphs, list):
        data["paragraphs"] = raw_paragraphs
    elif isinstance(raw_paragraphs, str):
        stripped = raw_paragraphs.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                data["paragraphs"] = [str(p).strip() for p in parsed if str(p).strip()]
            else:
                data["paragraphs"] = [p.strip() for p in raw_paragraphs.split("\n\n") if p.strip()]
        else:
            data["paragraphs"] = [p.strip() for p in raw_paragraphs.split("\n\n") if p.strip()]
    else:
        data["paragraphs"] = _ensure_string_list(raw_paragraphs)

    data["tags"] = _ensure_string_list(data.get("tags"))

    if not data.get("usable", False):
        return None

    data.setdefault("source_name", article["source"])
    if published_str:
        data["published_date"] = published_str
    else:
        data.setdefault("published_date", None)
    data["link"] = article["link"]
    # Az eredeti forráskulcsot (pl. "wantedinrome.com") KÜLÖN is eltároljuk -
    # lásd a hegycsucsok_digest.py-ban is alkalmazott azonos indoklást.
    data["source_key"] = article["source"]

    if not data.get("image_url"):
        query = data.get("image_search_query") or "Rome Italy"
        found = search_openverse_image(query)
        if found:
            data["image_url"] = found["image_url"]
            data["image_credit"] = found["image_credit"]
            data["image_location"] = found["image_location"]

    # --- MINŐSÉGBIZTOSÍTÁSI LÉPÉS: roma_keyword_scorer a KÉSZ magyar
    # szövegen. NEM dönt a be/ki-kerülésről, csak egy pontszámot csatol.
    score_result = score_article(
        data.get("title", ""), data.get("lead", ""),
        " ".join(data.get("paragraphs", [])),
    )
    data["roma_pontszam"] = score_result.total_score
    data["roma_cim_lead_talalat"] = score_result.title_or_lead_match
    if score_result.total_score == 0:
        print(f"  FIGYELEM: '{data.get('title')}' Róma-pontszáma 0 a kész "
              f"magyar szövegen - érdemes emberi felülvizsgálatra.")

    return data


# ---------------------------------------------------------------------------
# 5. WORDPRESS PISZKOZAT-LÉTREHOZÁS (amoreroma.hu - sima "post" post type,
#    ACF MEZŐK NÉLKÜL - lásd a modul-docstringet)
# ---------------------------------------------------------------------------

_term_cache = {}


def wp_headers(user, app_password, with_content_type=False):
    token = base64.b64encode(f"{user}:{app_password}".encode("utf-8")).decode("ascii")
    headers = dict(WP_API_HEADERS)
    headers["Authorization"] = f"Basic {token}"
    headers["Accept"] = "application/json"
    if with_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def wp_get_or_create_term(taxonomy_rest_base, name, wp_user, wp_app_password, site_url):
    if not name:
        return None

    cache_key = (taxonomy_rest_base, name.strip().lower())
    if cache_key in _term_cache:
        return _term_cache[cache_key]

    base = f"{site_url}/wp-json/wp/v2/{taxonomy_rest_base}"

    resp = None
    try:
        resp = requests.get(
            base,
            params={"search": name, "per_page": 100},
            headers=wp_headers(wp_user, wp_app_password),
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json()
        if not isinstance(results, list):
            raise ValueError(f"Váratlan válaszformátum (nem lista): {results}")
        for term in results:
            if term["name"].strip().lower() == name.strip().lower():
                _term_cache[cache_key] = term["id"]
                return term["id"]
    except Exception as e:
        detail = resp.text[:300] if resp is not None else ""
        print(f"    Hiba a(z) '{name}' term keresésekor ({taxonomy_rest_base}): {e} | Válasz: {detail}")

    resp = None
    try:
        resp = requests.post(
            base,
            json={"name": name},
            headers=wp_headers(wp_user, wp_app_password, with_content_type=True),
            timeout=15,
        )
        resp.raise_for_status()
        result = resp.json()
        if not isinstance(result, dict) or "id" not in result:
            raise ValueError(f"Váratlan válaszformátum (nincs 'id'): {result}")
        term_id = result["id"]
        _term_cache[cache_key] = term_id
        return term_id
    except Exception as e:
        detail = resp.text[:300] if resp is not None else ""
        print(f"    Hiba a(z) '{name}' term létrehozásakor ({taxonomy_rest_base}): {e} | Válasz: {detail}")
        return None


def _ascii_safe_filename(url, content_type):
    parsed_path = re.sub(r"[?#].*$", "", url.rsplit("/", 1)[-1])
    base_ascii = re.sub(r"[^A-Za-z0-9._-]", "", parsed_path)
    if not base_ascii or "." not in base_ascii:
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".jpg"
        base_ascii = f"image{ext}"
    return base_ascii[:100]


def wp_upload_media(image_url, alt_text, caption, wp_user, wp_app_password, site_url):
    if not image_url:
        return None

    try:
        img_resp = requests.get(image_url, headers=ARTICLE_FETCH_HEADERS, timeout=20)
        img_resp.raise_for_status()
        image_bytes = img_resp.content
        content_type = img_resp.headers.get("Content-Type", "").split(";")[0].strip() or "image/jpeg"
    except Exception as e:
        print(f"    Hiba a kép letöltésekor ({image_url}): {e}")
        return None

    filename = _ascii_safe_filename(image_url, content_type)

    headers = wp_headers(wp_user, wp_app_password)
    headers["Content-Type"] = content_type
    headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    resp = None
    try:
        resp = requests.post(
            f"{site_url}/wp-json/wp/v2/media",
            data=image_bytes,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        if not isinstance(result, dict) or "id" not in result:
            raise ValueError(f"Váratlan válaszformátum (nincs 'id'): {result}")
        media_id = result["id"]
    except Exception as e:
        detail = resp.text[:300] if resp is not None else ""
        print(f"    Hiba a kép feltöltésekor a médiatárba: {e} | Válasz: {detail}")
        return None

    if alt_text or caption:
        media_meta = {"alt_text": (alt_text or "")[:200]}
        if alt_text:
            media_meta["title"] = alt_text[:200]
        if caption:
            media_meta["caption"] = f"Forrás: {caption}"
        try:
            requests.post(
                f"{site_url}/wp-json/wp/v2/media/{media_id}",
                json=media_meta,
                headers=wp_headers(wp_user, wp_app_password, with_content_type=True),
                timeout=15,
            )
        except Exception as e:
            print(f"    Figyelmeztetés: nem sikerült beállítani a kép alt-szövegét/forrását: {e}")

    return media_id


def linkify_source_mention(paragraphs, source_key):
    """Lásd a hegycsucsok_digest.py azonos nevű függvényét - itt szó szerint
    ugyanaz a logika: az ELSŐ előfordulást linkeli a forrás FŐOLDALÁRA."""
    homepage_url = SOURCE_HOMEPAGES.get(source_key)
    if not homepage_url or not source_key:
        return paragraphs

    pattern = re.compile(re.escape(source_key), re.IGNORECASE)
    result = []
    linked = False
    for p in paragraphs:
        if not linked:
            m = pattern.search(p)
            if m:
                link_html = (
                    f'<a href="{homepage_url}" target="_blank" '
                    f'rel="noopener">{m.group(0)}</a>'
                )
                p = p[:m.start()] + link_html + p[m.end():]
                linked = True
        result.append(p)

    if not linked:
        print(f"    Figyelmeztetés: a(z) '{source_key}' forrásnév szó szerinti "
              f"formában nem található a cikkszövegben - a forráshivatkozás "
              f"linkelése ezúttal kimaradt.")

    return result


def render_content_html(article_json):
    """Lásd a hegycsucsok_digest.py azonos nevű függvényét - a bekezdéseket
    a forrás-linkeléssel adja vissza, a végére pedig - ha van kép-
    hitelesítés - egy "Képek forrása: ..." bekezdést fűz (ACF mező helyett,
    mert az amoreroma.hu-n jelenleg nincsenek ACF mezők)."""
    paragraphs = linkify_source_mention(
        article_json.get("paragraphs", []),
        article_json.get("source_key", ""),
    )

    html_parts = [f"<p>{p}</p>" for p in paragraphs]

    image_credit = article_json.get("image_credit")
    if image_credit:
        html_parts.append(f"<p><em>Képek forrása: {image_credit}</em></p>")

    return "\n".join(html_parts)


def wp_create_draft(article_json):
    """Piszkozatot hoz létre az amoreroma.hu SIMA 'posts' végpontján.
    ACF mezőket NEM használunk. Kategóriaként a Róma-i negyedet/környéket
    használjuk, ha van (a 'country' mező helyett, mert itt gyakorlatilag
    mindig Olaszország/Róma a helyszín - egy negyed/kerület informatívabb
    kategória)."""
    site_url = os.environ["AMOREROMA_WP_SITE_URL"].rstrip("/")
    wp_user = os.environ["AMOREROMA_WP_USER"]
    wp_app_password = os.environ["AMOREROMA_WP_APP_PASSWORD"]

    tag_ids = []
    for tag_name in article_json.get("tags") or []:
        term_id = wp_get_or_create_term("tags", tag_name, wp_user, wp_app_password, site_url)
        if term_id:
            tag_ids.append(term_id)

    category_ids = []
    district = article_json.get("district")
    if district:
        term_id = wp_get_or_create_term("categories", district, wp_user, wp_app_password, site_url)
        if term_id:
            category_ids.append(term_id)

    content_html = render_content_html(article_json)

    featured_media_id = None
    image_url = article_json.get("image_url")
    if image_url:
        alt_text = article_json.get("image_location") or article_json.get("title") or ""
        caption = article_json.get("image_credit") or ""
        featured_media_id = wp_upload_media(
            image_url, alt_text, caption, wp_user, wp_app_password, site_url
        )
        if featured_media_id is None:
            print(f"    Figyelmeztetés: nem sikerült feltölteni a kiemelt képet "
                  f"('{article_json.get('title')}') - a poszt kép nélkül jön létre.")

    payload = {
        "title": article_json["title"],
        "content": content_html,
        "excerpt": article_json.get("lead", ""),
        "status": "draft",
        "tags": tag_ids,
        "categories": category_ids,
    }
    if featured_media_id:
        payload["featured_media"] = featured_media_id

    resp = None
    try:
        resp = requests.post(
            f"{site_url}/wp-json/wp/v2/posts",
            json=payload,
            headers=wp_headers(wp_user, wp_app_password, with_content_type=True),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or "id" not in data:
            raise ValueError(f"Váratlan válaszformátum (nincs 'id') - valószínűleg "
                              f"hosting-szintű blokkolás, nem valódi WP-válasz: {data}")
        return data.get("link") or f"{site_url}/wp-admin/post.php?post={data['id']}&action=edit"
    except Exception as e:
        detail = resp.text[:300] if resp is not None else ""
        print(f"  Hiba a WordPress-piszkozat létrehozásakor ('{article_json.get('title')}'): {e} | Válasz: {detail}")
        return None


# ---------------------------------------------------------------------------
# 6. EMAIL ÖSSZEÁLLÍTÁS ÉS KÜLDÉS
# ---------------------------------------------------------------------------

def render_email_section(article_json, wp_link):
    lines = [f"## {article_json['title']}", "", f"*{article_json.get('lead', '')}*", ""]
    lines.extend(article_json.get("paragraphs", []))
    lines.append("")

    if article_json.get("image_url"):
        caption = article_json.get("image_credit") or ""
        lines.append(f"**Kép:** {article_json['image_url']}")
        if caption:
            lines.append(f"*{caption}*")
        lines.append("")

    published = article_json.get("published_date") or "dátum ismeretlen"
    lines.append(f"**Forrás:** {article_json.get('source_name', '')}, megjelent {published}")

    conf = "magas (cím/lead-ben is van találat)" if article_json.get("roma_cim_lead_talalat") else "közepes (csak törzsszövegben)"
    lines.append(f"**Róma-pontszám:** {article_json.get('roma_pontszam', 0)}  (bizalmi szint: {conf})")

    if wp_link:
        lines.append(f"\n📤 **Piszkozatként feltöltve:** {wp_link}")

    recovery_data = {
        "title": article_json.get("title"),
        "lead": article_json.get("lead"),
        "paragraphs": article_json.get("paragraphs", []),
        "image_url": article_json.get("image_url"),
        "image_credit": article_json.get("image_credit"),
        "image_location": article_json.get("image_location"),
        "source_name": article_json.get("source_name"),
        "source_key": article_json.get("source_key"),
        "published_date": article_json.get("published_date"),
        "district": article_json.get("district"),
        "tags": article_json.get("tags", []),
        "link": article_json.get("link"),
        "roma_pontszam": article_json.get("roma_pontszam", 0),
        "roma_cim_lead_talalat": article_json.get("roma_cim_lead_talalat", False),
        "already_uploaded": bool(wp_link),
    }
    lines.append("")
    lines.append(f"[ADATOK: {json.dumps(recovery_data, ensure_ascii=False)}]")

    return "\n".join(lines)


def send_email(subject, body_markdown):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    email_from = os.environ.get("EMAIL_FROM", smtp_user)
    email_to = os.environ["AMOREROMA_EMAIL_TO"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.attach(MIMEText(body_markdown, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(email_from, email_to.split(","), msg.as_string())


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

REQUIRED_ENV_VARS = [
    "ANTHROPIC_API_KEY",
    "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM",
    "AMOREROMA_EMAIL_TO",
    "AMOREROMA_WP_SITE_URL", "AMOREROMA_WP_USER", "AMOREROMA_WP_APP_PASSWORD",
]


def validate_env():
    """Fail-fast ellenőrzés a futás legelején: ha egy szükséges GitHub
    Secret hiányzik VAGY üres string (pl. elgépelt secret-név, vagy be sem
    lett állítva), itt egyetlen, egyértelmű hibaüzenettel álljon meg a
    script - ne 10+ kusza "Invalid URL" / SMTP hibán keresztül derüljön ki
    a végén, ahogy egy korábbi éles futásnál történt."""
    missing = [name for name in REQUIRED_ENV_VARS if not os.environ.get(name)]
    if missing:
        print("HIBA: a következő GitHub Secret(ek) hiányoznak vagy üresek: "
              + ", ".join(missing))
        print("Ellenőrizd a repó Settings → Secrets and variables → Actions "
              "alatt, hogy pontosan ezekkel a nevekkel léteznek-e, és van-e "
              "értékük.")
        raise SystemExit(1)


def main():
    validate_env()
    candidates = collect_candidates()
    print(f"Talált (előszűrt) jelölt: {len(candidates)}")

    ranked = select_and_rank(candidates)
    print(f"Róma-témájú AI-válogatás után megmaradt: {len(ranked)}")

    summaries = []
    for i, article in enumerate(ranked):
        if len(summaries) >= DAILY_TOTAL_LIMIT:
            print(f"Elértük a napi limitet ({DAILY_TOTAL_LIMIT} sikeres cikk) - "
                  f"a maradék {len(ranked) - i} tartalék cikket nem dolgozzuk fel.")
            break

        print(f"Feldolgozás ({i + 1}/{len(ranked)}, eddig {len(summaries)}/{DAILY_TOTAL_LIMIT} sikeres): "
              f"[{article['source']}] {article['title']}")
        try:
            content = fetch_article_content(
                article["link"],
                rss_fallback_html=article.get("rss_full_content", ""),
            )
            summary = summarize_article(article, content)
            if summary is None:
                print(f"  Kihagyva: nem volt elég Róma-témájú tartalom egy önálló cikkhez.")
                continue
            summaries.append(summary)
        except Exception as e:
            print(f"  Hiba az összefoglalásnál: {e}")
        time.sleep(1)

    print(f"\nVégeredmény: {len(summaries)}/{DAILY_TOTAL_LIMIT} sikeres cikk.")

    wp_links = {}
    for summary in summaries:
        link = wp_create_draft(summary)
        if link:
            wp_links[summary["link"]] = link
            print(f"  Piszkozat létrehozva: {link}")

    today_str = datetime.now().strftime("%Y. %m. %d.")

    if not summaries:
        body = f"Ma ({today_str}) nem találtunk Róma-témájú cikket a beállított források friss híranyagában."
    else:
        sections = [
            render_email_section(s, wp_links.get(s["link"]))
            for s in summaries
        ]
        body = f"# Napi Róma-hír-digest (amoreroma.hu) - {today_str}\n\n" + "\n\n---\n\n".join(sections)

    subject = f"Róma-hírek (amoreroma.hu) - {today_str}"
    send_email(subject, body)
    print("Email elküldve.")


if __name__ == "__main__":
    main()
