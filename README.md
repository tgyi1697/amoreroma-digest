# amoreroma-digest

Napi Róma-témájú hír-digest az amoreroma.hu oldalhoz. A
`vizpartok_digest.py` (vizpartok.hu) bevált mintáját követi - lásd az
`amoreroma_digest.py` fájl fejlécében a részletes leírást.

## Fájlok

- `amoreroma_digest.py` - fő script (RSS-begyűjtés → AI-válogatás →
  összefoglalás → WP-piszkozat → email)
- `roma_keyword_scorer.py` - utólagos minőségbiztosítási pontozó
- `email_recovery_upload.py` - email-alapú WP-helyreállító (ha a piszkozat-
  létrehozás elesik, pl. Imunify360 blokkolás miatt)
- `recovery-upload.yml` - GitHub Actions workflow a helyreállításhoz
  (`.github/workflows/` alá másolandó, kézi indítású)
- `amoreroma-daily-digest.yml` - GitHub Actions workflow (`.github/workflows/`
  alá másolandó)
- `requirements.txt` - Python-függőségek

## Helyreállítás (ha a WP-feltöltés elesik, de az email kiment)

1. Mentsd le a digest emailt `.eml` fájlként (vagy másold ki a szöveges
   törzsét egy `.txt` fájlba).
2. Töltsd fel a repóba `recovery_email.eml` (vagy `recovery_email.txt`)
   néven.
3. Actions fül → "Email-alapú WordPress helyreállítás (amoreroma.hu)" →
   Run workflow.

A script automatikusan kihagyja azokat a cikkeket, amik már sikeresen
feltöltődtek (az email "📤 Piszkozatként feltöltve" jelölése vagy az
`[ADATOK: ...]` blokk `already_uploaded: true` mezője alapján) - nem
hoz létre duplikátumot.

## Beállítás

1. Hozz létre egy Application Password-öt az amoreroma.hu WordPress
   admin felületén (Felhasználók → Profil → Application Passwords).
2. Állítsd be a GitHub Secrets-eket (Settings → Secrets and variables →
   Actions), **10 db**:
   - `ANTHROPIC_API_KEY`
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
   - `AMOREROMA_EMAIL_TO`
   - `AMOREROMA_WP_SITE_URL`
   - `AMOREROMA_WP_USER`
   - `AMOREROMA_WP_APP_PASSWORD`
3. Másold az `amoreroma-daily-digest.yml`-t a `.github/workflows/`
   könyvtárba.
4. Első futtatás: GitHub Actions fülön "Run workflow" (workflow_dispatch) -
   ne várd meg a napi cron-t, hogy gyorsan lásd, működik-e minden.

## Nyitott pontok, amiket érdemes az első pár futás után átnézni

- **reuters.com forrás**: a Reuters 2020 óta nem ad ki saját RSS-t, ezért
  egy Google News-alapú proxy-feedet használunk (`REUTERS_FEED_URL` a
  scriptben). Érdemes megnézni a futási logban, hogy hoz-e egyáltalán
  releváns, letölthető cikkeket.
- **romatoday.it forrás**: a felhasználó egy feedreader-nézettel
  megerősítette, hogy a feed (`https://www.romatoday.it/rss`, záró perjel
  NÉLKÜL) élesben működik és tartalmat is ad - a korábbi üres/403-as
  eredmény valószínűleg a záró perjeles URL-változat miatt volt, ez már
  javítva van a scriptben. A feed tartalma viszont túlnyomórészt helyi
  közéleti/bűnügyi/közlekedési hír, ezért szigorú kulcsszó-előszűréssel +
  AI-válogatással kezeljük - érdemes az első pár futás
  "Forrásonkénti bontás" logját megnézni, mennyi valóban releváns találat
  jön belőle.
- **WordPress-struktúra**: az amoreroma.hu ACF-mezői/egyéni taxonómiái
  MÉG NINCSENEK feltérképezve. A `wp_create_draft()` jelenleg a
  vizpartok.hu-nál bevált, ACF nélküli mintát követi (sima "posts"
  végpont, kategória + címke taxonómia, natív featured_media kép) - a
  kategóriát a Róma-i negyed/környék adja (nem az ország, mint a másik két
  digestnél, mert itt gyakorlatilag mindig Olaszország/Róma a helyszín).
  Ha kiderül, hogy vannak/lesznek ACF mezők, ezt a függvényt érdemes
  felülvizsgálni.
- **DAILY_TOTAL_LIMIT/PURE_SOURCE_DAILY_LIMIT**: a vizpartok.hu-nál bevált
  6/2 értékkel indulunk - finomítható az első pár hetes tapasztalat
  alapján.
- **roma_keyword_scorer.py küszöbértéke**: placeholder, valós cikkeken
  tesztelve finomítandó.

## Facebook-posztolás

Jelenleg NEM része ennek a projektnek - a felhasználó kérése szerint
opcionálisan, később kerülhet szóba (a vizpartok.hu-s Facebook-modul
mintájára).
