# xeen

Screenshot capture → edit → crop → publish. One command.

```
pip install -e .
xeen
```

## Problem

Chcesz szybko stworzyć krótki film ze screenshotów — demo produktu, tutorial, changelog.
Ale Canva to za dużo kroków. `xeen` robi to w terminalu + przeglądarce.

## Jak działa

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Capture │ ──→ │  Select  │ ──→ │  Center  │ ──→ │   Crop   │ ──→ │ Publish  │
│ xeen c  │     │  Tab 1   │     │  Tab 2   │     │  Tab 3-4 │     │  Tab 5   │
└─────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
 screenshoty     wybór klatek     środek uwagi     przycinanie       eksport
 + metadane      grid view        click = center   presety SM        MP4/GIF/ZIP
 kursor/kb       max 15           auto z kursora   multi-wersje      social links
```

## Instalacja

```bash
# Z repozytorium
git clone https://github.com/softreck/xeen.git
cd xeen
pip install -e .

# Wymagania systemowe
# Linux/Mac: ffmpeg
sudo apt install ffmpeg   # Ubuntu/Debian
brew install ffmpeg        # macOS
```

## Użycie

### 1. Nagrywanie

```bash
# Domyślne (10s, co 1s, max 15 klatek)
xeen capture

# Krótkie demo (5s)
xeen capture -d 5

# Gęstsze klatki
xeen capture -d 10 -i 0.5

# Nazwana sesja
xeen capture -n "ksefin-demo-v2"

# Konkretny monitor
xeen capture --monitor 1
```

Co zbiera `xeen capture`:
- **Screenshoty** z inteligentnym interwałem (pomija identyczne klatki)
- **Pozycja myszy** co 100ms — używana jako sugestia "środka uwagi"
- **Klawisze** — log co zostało wciśnięte (kontekst)
- **% zmiany ekranu** — między klatkami

### 2. Edycja w przeglądarce

```bash
# Uruchom serwer (otwiera przeglądarkę)
xeen

# Lub jawnie
xeen server -p 8080
xeen server --no-browser
```

**5 zakładek:**

| Tab | Funkcja |
|-----|---------|
| 1. Wybór klatek | Grid wszystkich klatek, kliknij aby wybrać/odrzucić |
| 2. Środek | Kliknij na obrazie = punkt centralny. Auto-sugestia z pozycji kursora |
| 3. Przycinanie | Wybierz preset (Instagram, Twitter, LinkedIn...) → podgląd przycięcia wg środka |
| 4. Wersje | Generuj kilka formatów naraz, porównaj obok siebie |
| 5. Publikacja | Eksport MP4/GIF/ZIP + linki do social media |

### 3. Upload zewnętrznych screenshotów

Możesz też przeciągnąć pliki PNG/JPG bezpośrednio do przeglądarki (Tab 1) — bez `xeen capture`.

### 4. Lista sesji

```bash
xeen list
```

## Presety przycinania

| Preset | Rozmiar | Użycie |
|--------|---------|--------|
| `instagram_post` | 1080×1080 | Post IG (kwadrat) |
| `instagram_story` | 1080×1920 | Story IG (9:16) |
| `twitter_post` | 1200×675 | Post Twitter/X |
| `linkedin_post` | 1200×627 | Post LinkedIn |
| `facebook_post` | 1200×630 | Post Facebook |
| `youtube_thumb` | 1280×720 | Miniatura YT |
| `widescreen` | 1920×1080 | 16:9 |

## Deploy na VPS (Docker + TLS)

```bash
# 1. Sklonuj na VPS
git clone https://github.com/softreck/xeen.git
cd xeen

# 2. Deploy z domeną
make deploy DOMAIN=xeen.twoja-domena.pl

# Lub ręcznie:
bash deploy.sh xeen.twoja-domena.pl
```

Skrypt automatycznie:
- Instaluje Docker + certbot
- Generuje cert TLS (Let's Encrypt lub self-signed)
- Buduje i uruchamia kontenery
- Konfiguruje auto-renewal

### Docker ręcznie

```bash
# Dev z self-signed cert
make dev-certs
docker-compose up -d

# Logi
docker-compose logs -f

# Stop
docker-compose down
```

### Struktura Docker

```
┌─────────────┐     ┌───────────┐
│   nginx     │────→│  xeen app │
│  :80/:443   │     │   :7600   │
│  TLS term.  │     │  FastAPI  │
└─────────────┘     └───────────┘
       │                   │
       │              ┌────┴────┐
       │              │  /data  │
       │              │ volume  │
       └──────────────┴─────────┘
```

## Metadane

Każda sesja zapisuje `session.json` z:

```json
{
  "name": "20250219_143022",
  "frames": [
    {
      "index": 0,
      "timestamp": 0.0,
      "filename": "frame_0000.png",
      "change_pct": 100.0,
      "mouse_x": 960,
      "mouse_y": 540,
      "suggested_center_x": 960,
      "suggested_center_y": 540,
      "input_events": [
        {"ts": 0.1, "kind": "mouse_move", "x": 955, "y": 538},
        {"ts": 0.2, "kind": "key_press", "key": "a", "x": 955, "y": 538},
        {"ts": 0.3, "kind": "mouse_click", "x": 960, "y": 540, "button": "Button.left"}
      ]
    }
  ],
  "input_log": [ ... ]  
}
```

## API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/sessions` | GET | Lista sesji |
| `/api/sessions/{name}` | GET | Szczegóły sesji |
| `/api/sessions/upload` | POST | Upload screenshotów |
| `/api/sessions/{name}/select` | POST | Zapisz wybór klatek |
| `/api/sessions/{name}/centers` | POST | Zapisz środki |
| `/api/sessions/{name}/crop-preview` | POST | Podgląd przycinania |
| `/api/sessions/{name}/generate-versions` | POST | Multi-format |
| `/api/sessions/{name}/export` | POST | Eksport MP4/GIF/ZIP |
| `/api/presets` | GET | Presety formatów |
| `/api/social-links` | GET | Linki social media |

## Licencja

MIT — Softreck

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

## Author

Created by **Tom Sapletta** - [tom@sapletta.com](mailto:tom@sapletta.com)
