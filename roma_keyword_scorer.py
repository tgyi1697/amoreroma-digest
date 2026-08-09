# -*- coding: utf-8 -*-
"""
roma_keyword_scorer.py
------------------------
Róma-téma pontozó az amoreroma.hu digest projekthez.

Ugyanaz a szerep, mint a vizpartok.hu-s water_keyword_scorer.py-nak: az
amoreroma_digest.py egy UTÓFELDOLGOZÓ lépéseként fut le a Claude-generálta
kész magyar cikkszövegen, és pontozza, mennyire "Róma-témájú" a hír. NEM
dönt a be/ki-kerülésről (azt már a select_and_rank AI-válogatás eldöntötte)
- csak egy minőségbiztosítási/bizalmi jelzőt csatol.

A súlyok és a küszöbérték EZ IS egy első minta, valós cikkeken tesztelve
finomítandó.
"""

import re
from dataclasses import dataclass, field


KEYWORDS = {
    # Konkrét Róma-helyszínek/entitások - a legerősebb jel
    "roma_hely": {
        "weight": 3,
        "patterns": [
            r"\bróma\w*", r"\bvatikán\w*", r"\bkolosszeum\w*",
            r"\btrastevere\w*", r"\bpalatinus\w*", r"\bpantheon\w*",
            r"\blazio\b", r"\bcampo dei fiori\w*", r"\bvia appia\w*",
            r"\bforum romanum\w*", r"\btrevi\w*", r"\bszent péter\w*",
        ],
    },
    # Műemlék/kulturális kontextus - közepes súly
    "muemlek_kultura": {
        "weight": 2,
        "patterns": [
            r"\bműemlék\w*", r"\btemplom\w*", r"\bbazilika\w*",
            r"\bmúzeum\w*", r"\bkiállítás\w*", r"\bszökőkút\w*",
            r"\bpalota\w*", r"\brégészet\w*", r"\básatás\w*",
            r"\bókori\w*", r"\bromos\w*",
        ],
    },
    # Romantika/esküvő - önmagában gyengébb jel, legkisebb súly
    "romantika_eskuvo": {
        "weight": 1,
        "patterns": [
            r"\besküvő\w*", r"\bnászút\w*",
            r"\bromantik\w*", r"\bjegyesség\w*",
        ],
    },
}

DEFAULT_THRESHOLD = 3


@dataclass
class ScoreResult:
    total_score: int
    matched: dict = field(default_factory=dict)
    is_roma_related: bool = False
    title_or_lead_match: bool = False
    title_matches: list = field(default_factory=list)
    lead_matches: list = field(default_factory=list)


def score_article(title: str, lead: str, content: str,
                   threshold: int = DEFAULT_THRESHOLD) -> ScoreResult:
    """Azonos logika, mint a water_keyword_scorer.score_article()-nél."""
    full_text = " ".join([title or "", lead or "", content or ""])

    matched = {}
    total = 0
    title_matches = []
    lead_matches = []

    for category, cfg in KEYWORDS.items():
        weight = cfg["weight"]
        hits = []
        for pattern in cfg["patterns"]:
            if re.search(pattern, full_text, flags=re.IGNORECASE):
                hits.append(pattern)
                if re.search(pattern, title or "", flags=re.IGNORECASE):
                    title_matches.append(pattern)
                if re.search(pattern, lead or "", flags=re.IGNORECASE):
                    lead_matches.append(pattern)
        if hits:
            matched[category] = hits
            total += weight * len(hits)

    return ScoreResult(
        total_score=total,
        matched=matched,
        is_roma_related=(total >= threshold),
        title_or_lead_match=bool(title_matches or lead_matches),
        title_matches=title_matches,
        lead_matches=lead_matches,
    )


if __name__ == "__main__":
    samples = [
        {
            "label": "Ókori lelet a Palatinuson (minta)",
            "title": "Ritka mozaikpadlót tártak fel a Palatinus lejtőjén",
            "lead": "A régészek szerint a lelet a császárkorból származhat.",
            "content": "A Kolosszeum közelében folyó ásatás során bukkantak "
                       "a mozaikra, amely egy ókori villa részét képezhette.",
        },
        {
            "label": "Autókölcsönzős hír (nem Róma-témájú, kontroll-teszt)",
            "title": "Új szabályok léptek életbe az autókölcsönzőknél",
            "lead": "Januártól szigorúbb feltételek mellett bérelhetünk autót.",
            "content": "A biztosítási díjak is emelkedtek.",
        },
    ]
    for sample in samples:
        result = score_article(sample["title"], sample["lead"], sample["content"])
        print(f"\n=== {sample['label']} ===")
        print(f"Pontszám: {result.total_score} (küszöb: {DEFAULT_THRESHOLD}) "
              f"-> Róma-témájú: {result.is_roma_related}")
        for category, hits in result.matched.items():
            print(f"  [{category}] találatok: {hits}")
