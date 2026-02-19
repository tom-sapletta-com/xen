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
┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ Capture │──→│ 1.Select │──→│2.Annotate│──→│ 3.Center │──→│  4.Crop  │──→│5.Captions│──→│6.Publish │
│ xeen    │   │ klatki   │   │ strzałki │   │ fokus    │   │ presety  │   │ napisy   │   │ eksport  │
└─────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
 screenshoty   wybór/usuw.    rysowanie      click=center   SM formaty     ręczne/AI      MP4/GIF/
 + metadane    duplikaty      tekst, rect    interpolacja   zoom/pad       LLM gen.       WebM/ZIP
 kursor/kb     sortowanie     kolory         auto z myszy   smart crop     drag&drop      branding
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

# Capture wymaga środowiska GUI, ale xeen automatycznie wykrywa
# najlepszą metodę i przełącza się na przeglądarkę gdy brak ekranu:
#
#   1. mss (X11/Wayland) → najszybszy
#   2. Pillow ImageGrab   → alternatywa
#   3. scrot/grim/import  → narzędzia systemowe
#   4. Przeglądarka (Screen Capture API) → fallback headless
#   5. Upload ręczny      → zawsze działa
```

## Użycie

### 1. Nagrywanie

```bash
# Domyślne (10s, co 1s, max 15 klatek) - komenda 'xeen' sama robi capture
xeen

# Lub jawnie
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

**6 zakładek:**

| Tab | Funkcja | Narzędzia |
|-----|---------|-----------|
| 1. Wybór klatek | Grid klatek — kliknij aby zaznaczyć/usunąć | Duplikaty, sortowanie, odwróć, co N-ta, pierwsze N, zakres czasu, największe zmiany |
| 2. Adnotacje | Rysuj strzałki, prostokąty, tekst na klatkach | Strzałka, prostokąt, tekst, kolory, grubość, cofnij, wyczyść |
| 3. Środek | Kliknij na obrazie = punkt fokus | Auto (kursor), środek obrazu, kopiuj do wszystkich, interpoluj, wyczyść |
| 4. Przycinanie | Preset (Instagram, Twitter, LinkedIn...) → podgląd | Podgląd wszystkich, dopasuj do treści, własny format, resetuj, zoom/pad |
| 5. Napisy | Dodaj opisy — ręcznie lub przez AI (LLM) | Dodaj, auto 1/klatka, AI generowanie (OpenAI/Anthropic/Ollama/Gemini), drag&drop |
| 6. Publikacja | Eksport MP4/GIF/WebM/ZIP + branding + social links | Szybki eksport, eksport wszystkich, znak wodny, folder, kopiuj link |

### 3. Automatyczny fallback capture

Gdy `xeen` nie może przechwycić ekranu (headless, brak GUI), automatycznie:

1. Próbuje kolejne backendy: `mss` → `Pillow` → `scrot`/`grim`/`import`
2. Jeśli żaden nie działa — **uruchamia serwer z trybem Browser Capture**
3. Przeglądarka otworzy stronę `http://127.0.0.1:7600/capture`
4. Użyj **Screen Capture API** (getDisplayMedia) do nagrania ekranu z przeglądarki

```bash
# Automatyczny fallback — xeen sam wykryje co działa
xeen

# Lub ręcznie uruchom browser capture
xeen server
# → otwórz http://127.0.0.1:7600/capture
```

### 4. Upload ręczny

Alternatywnie, w edytorze (Tab 1):
- **Przeciągnij pliki PNG/JPG** bezpośrednio na stronę
- **Kliknij "Wybierz pliki"** aby wybrać screenshoty z komputera

### 5. Lista sesji

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

## Szybka prezentacja z 3-5 zrzutów ekranu

Najszybszy workflow do stworzenia demo/tutoriala:

```bash
# 1. Zrób 3-5 zrzutów ekranu (PrintScreen, Flameshot, itp.)
# 2. Uruchom xeen
xeen server

# 3. W przeglądarce:
#    Tab 1: Przeciągnij screenshoty → zaznacz potrzebne
#    Tab 3: Kliknij "Auto: kursor myszy" (lub ustaw ręcznie)
#    Tab 4: Wybierz preset np. twitter_post
#    Tab 6: Kliknij "Generuj wszystkie formaty"
```

**Wskazówki:**
- **3 zrzuty** — idealnie na social media post (Twitter, LinkedIn)
- **5 zrzutów** — dobra ilość na krótki tutorial/changelog
- **Pomiń Tab 2 (Adnotacje)** jeśli screenshoty są czytelne
- **Pomiń Tab 5 (Napisy)** jeśli nie potrzebujesz opisów
- Użyj **"Pierwsze N"** w Tab 1 aby szybko wybrać dokładnie tyle klatek ile potrzebujesz
- Ustaw **focus=mouse + pad=20%** aby wyciąć istotny fragment ekranu

## FPS — ile klatek nagrywać?

| Interwał | FPS | Zastosowanie |
|----------|-----|-------------|
| `1.0s` | 1 | Statyczne demo — klik → screenshot → klik (domyślne) |
| `0.5s` | 2 | Płynniejsze prezentacje, więcej klatek do wyboru |
| `0.33s` | 3 | Najlepszy balans: płynność + rozsądna ilość klatek |

**Rekomendacja: 2-3 FPS** (`xeen capture -i 0.5` lub `-i 0.33`).
- Przy 1 FPS możesz przegapić krótkie interakcje
- Przy 3 FPS masz wystarczająco dużo materiału bez zalewania dysku
- Duplikaty można usunąć automatycznie w Tab 1 ("Znajdź duplikaty")

## API

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/api/sessions` | GET | Lista sesji |
| `/api/sessions/{name}` | GET | Szczegóły sesji |
| `/api/sessions/{name}/thumbnails` | GET | Miniaturki (max N) |
| `/api/sessions/upload` | POST | Upload screenshotów |
| `/api/sessions/{name}/select` | POST | Zapisz wybór klatek |
| `/api/sessions/{name}/update-frames` | POST | Aktualizuj listę klatek (po usunięciu/przywróceniu) |
| `/api/sessions/{name}/centers` | POST | Zapisz środki fokus |
| `/api/sessions/{name}/crop-preview` | POST | Podgląd przycinania (z custom_centers inline) |
| `/api/sessions/{name}/video-preview` | POST | Podgląd wideo (miniatura) |
| `/api/sessions/{name}/export` | POST | Eksport MP4/GIF/WebM/ZIP |
| `/api/sessions/{name}/captions` | POST | Zapisz napisy |
| `/api/sessions/{name}/captions/generate` | POST | Generuj napisy AI (LLM) |
| `/api/presets` | GET | Presety formatów |
| `/api/branding` | GET/POST | Konfiguracja znaku wodnego |
| `/api/social-links` | GET | Linki social media |

## Licencja

MIT — Softreck

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

## Author

Created by **Tom Sapletta** - [tom@sapletta.com](mailto:tom@sapletta.com)
