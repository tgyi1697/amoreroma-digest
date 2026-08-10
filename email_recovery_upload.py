#!/usr/bin/env python3
"""
Email-alapú WordPress-feltöltés helyreállító szkript (amoreroma.hu)
======================================================================
Arra való, hogy ha a napi amoreroma_digest.py lefutott és az email
KIMENT, de a WordPress-feltöltés valamiért elesett (pl. Imunify360
bot-blokkolás - lásd a wp_headers_imunify360_osszefoglalo.txt-t), ebből a
szkriptből pótolni lehessen a feltöltést, ANÉLKÜL, hogy újra le kellene
futtatni a teljes RSS-gyűjtést és AI-válogatást (ami pénzbe kerül és más
cikkeket választhatna).

Ez az email_recovery_upload.py (tourism-digest repó) 1:1 mintája - a
FELDOLGOZÁSI LOGIKA TELJESEN AZONOS (az "[ADATOK: ...]" JSON-blokk
formátuma megegyezik), az EGYETLEN érdemi különbség, hogy a
wp_create_draft()-ot az amoreroma_digest.py modulból importáljuk, hogy a
helyes (AMOREROMA_WP_SITE_URL / AMOREROMA_WP_USER /
AMOREROMA_WP_APP_PASSWORD) környezeti változókat és a Róma-témájú
forrás-linkelési logikát használja.

HASZNÁLAT:
1. Mentsd el a digest emailt .eml fájlként (a legtöbb levelezőkliens
   tud "Mentés mint .eml"-t), VAGY másold ki a szöveges törzsét egy
   .txt fájlba.
2. Töltsd fel ezt a fájlt a repóba, pl. "recovery_email.eml" néven
   (vagy "recovery_email.txt", ha txt-t használsz).
3. Futtasd le ezt a szkriptet (lásd a hozzá tartozó
   recovery-upload.yml GitHub Actions workflow-t - Actions fül →
   "Email-alapú WordPress helyreállítás (amoreroma.hu)" → Run workflow).

FONTOS - DUPLIKÁCIÓ ELKERÜLÉSE:
- Ha az email egy cikke MÁR tartalmazza a "📤 Piszkozatként feltöltve"
  jelölést (vagy az "[ADATOK: ...]" blokkban "already_uploaded": true
  szerepel), azt a szkript KIHAGYJA (már sikeresen fel lett töltve, nem
  kell újra).
- Minden amoreroma_digest.py által küldött email tartalmazza a rejtett
  "[ADATOK: ...]" sort minden cikk végén - ebből a szkript pontosan
  vissza tudja állítani a negyedet/környéket ("district"), a címkéket ÉS
  a forrás-linkeléshez szükséges "source_key" mezőt is.
"""

import os
import re
import sys
import json
import email
from email import policy

# Ugyanazt a wp_create_draft-ot hasznaljuk, mint az eles amoreroma_digest.py,
# hogy 1:1-ben ugyanaz a WordPress-feltoltesi logika fusson (kategoria/
# cimke automatikus letrehozasa, "Kepek forrasa:" bekezdes, forras-linkeles
# stb.)
from amoreroma_digest import wp_create_draft


def read_email_body(filepath):
    """Beolvassa a szoveges torzset egy .eml vagy .txt fajlbol."""
    if filepath.lower().endswith(".eml"):
        with open(filepath, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body_part = msg.get_body(preferencelist=("plain",))
        if not body_part:
            raise ValueError("Az .eml fájlban nem található szöveges (plain text) törzs.")
        return body_part.get_content()
    else:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()


def parse_sections(body_text):
    """A teljes email-torzset "---" hatarolokkal kulon cikk-szakaszokra
    bontja, es minden szakaszt strukturalt dict-te alakit."""
    first_marker = body_text.find("## ")
    if first_marker == -1:
        return []
    body_text = body_text[first_marker:]

    raw_sections = re.split(r"\n\n---\n\n", body_text.strip())
    articles = []

    for raw in raw_sections:
        raw = raw.strip()
        if not raw.startswith("## "):
            continue
        articles.append(parse_single_section(raw))

    return articles


def parse_single_section(raw):
    """Egyetlen cikk-szakasz szovegebol kinyeri a strukturalt adatokat."""
    lines = raw.split("\n")

    title = lines[0][3:].strip()  # "## " levagasa

    already_uploaded = "📤" in raw and "Piszkozatként feltöltve" in raw

    # Rejtett ADATOK blokk keresese
    adatok_match = re.search(r"\[ADATOK:\s*(\{.*\})\]", raw)
    if adatok_match:
        try:
            recovery_data = json.loads(adatok_match.group(1))
            recovery_data["link"] = recovery_data.get("link") or f"recovered:{title}"
            return recovery_data
        except json.JSONDecodeError:
            pass  # esunk vissza a szoveges feldolgozasra

    # --- Regi formatumu (ADATOK blokk nelkuli) email feldolgozasa ---
    lead = ""
    paragraphs = []
    image_url = None
    image_credit = None
    source_name = ""
    published_date = None

    i = 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i < len(lines) and lines[i].strip().startswith("*") and lines[i].strip().endswith("*"):
        lead = lines[i].strip().strip("*")
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("**Kép:**") or line.startswith("**Forrás:**") or line.startswith("📤") or line.startswith("[ADATOK:"):
            break
        if line:
            paragraphs.append(line)
        i += 1

    if i < len(lines) and lines[i].strip().startswith("**Kép:**"):
        image_url = lines[i].strip()[len("**Kép:**"):].strip()
        i += 1
        if i < len(lines) and lines[i].strip().startswith("*") and lines[i].strip().endswith("*"):
            image_credit = lines[i].strip().strip("*")
            i += 1

    while i < len(lines):
        line = lines[i].strip()
        m = re.match(r"\*\*Forrás:\*\*\s*(.+?),\s*megjelent\s*(.+)", line)
        if m:
            source_name = m.group(1).strip()
            published_date = m.group(2).strip()
            break
        i += 1

    return {
        "title": title,
        "lead": lead,
        "paragraphs": paragraphs,
        "image_url": image_url,
        "image_credit": image_credit,
        "image_location": None,
        "source_name": source_name,
        "source_key": source_name,
        "published_date": published_date,
        "district": None,
        "tags": [],
        "link": f"recovered:{title}",
        "already_uploaded": already_uploaded,
    }


def main():
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
    else:
        candidates = ["recovery_email.eml", "recovery_email.txt"]
        filepath = next((c for c in candidates if os.path.exists(c)), None)
        if not filepath:
            print("HIBA: nem található a 'recovery_email.eml' vagy "
                  "'recovery_email.txt' fájl a repó gyökerében, és nem "
                  "adtál meg elérési utat paraméterként.")
            sys.exit(1)

    print(f"Beolvasás: {filepath}")
    body = read_email_body(filepath)

    articles = parse_sections(body)
    print(f"Talált cikkek: {len(articles)}")

    uploaded = 0
    skipped = 0
    failed = 0

    for i, article in enumerate(articles, 1):
        if article.get("already_uploaded"):
            print(f"[{i}/{len(articles)}] KIHAGYVA (már fel volt töltve): {article['title']}")
            skipped += 1
            continue

        print(f"[{i}/{len(articles)}] Feltöltés: {article['title']}")
        link = wp_create_draft(article)
        if link:
            print(f"  -> Sikeres: {link}")
            uploaded += 1
        else:
            print(f"  -> HIBA a feltöltésnél (lásd fentebb a részletes hibaüzenetet)")
            failed += 1

    print(f"\n=== ÖSSZESÍTÉS ===")
    print(f"Feltöltve: {uploaded}")
    print(f"Kihagyva (már megvolt): {skipped}")
    print(f"Hiba: {failed}")


if __name__ == "__main__":
    main()
