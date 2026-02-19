.PHONY: install install-system install-pip install-venv dev capture server stop docker deploy clean check desktop desktop-dev desktop-build install-desktop

PYTHON  ?= python3
VENV    ?= venv
PIP     := $(VENV)/bin/pip
XEEN    := $(VENV)/bin/xeen

# ─── Pełna instalacja (system + pip + venv) ───────────────────────────────────
install: install-system install-venv
	@echo ""
	@echo "✅  xeen zainstalowany. Uruchom:"
	@echo "    source $(VENV)/bin/activate"
	@echo "    xeen server"

# Zależności systemowe (tesseract, ffmpeg, scrot)
install-system:
	@echo "📦  Instalacja zależności systemowych..."
	@if command -v apt-get >/dev/null 2>&1; then \
		sudo apt-get update -qq && \
		sudo apt-get install -y --no-install-recommends \
			tesseract-ocr \
			tesseract-ocr-pol \
			tesseract-ocr-eng \
			ffmpeg \
			scrot \
			xclip; \
	elif command -v dnf >/dev/null 2>&1; then \
		sudo dnf install -y tesseract tesseract-langpack-pol ffmpeg scrot; \
	elif command -v pacman >/dev/null 2>&1; then \
		sudo pacman -S --noconfirm tesseract tesseract-data-pol ffmpeg scrot; \
	elif command -v brew >/dev/null 2>&1; then \
		brew install tesseract tesseract-lang ffmpeg; \
	else \
		echo "⚠️  Nieznany menedżer pakietów — zainstaluj ręcznie: tesseract ffmpeg"; \
	fi

# Virtualenv + pip install
install-venv:
	@echo "🐍  Tworzenie virtualenv w ./$(VENV)..."
	@$(PYTHON) -m venv $(VENV)
	@echo "📦  Instalacja pakietów Python..."
	@$(PIP) install --upgrade pip setuptools wheel
	@$(PIP) install -e ".[dev]"
	@echo "🔍  Weryfikacja instalacji..."
	@$(VENV)/bin/python -c "import pytesseract; print('  ✅ pytesseract:', pytesseract.get_tesseract_version())" 2>/dev/null || \
		echo "  ⚠️  pytesseract: tesseract nie znaleziony w PATH (uruchom make install-system)"
	@$(VENV)/bin/python -c "import numpy; print('  ✅ numpy:', numpy.__version__)"
	@$(VENV)/bin/python -c "import PIL; print('  ✅ Pillow:', PIL.__version__)"
	@$(VENV)/bin/python -c "import fastapi; print('  ✅ fastapi:', fastapi.__version__)"

# Tylko pip (bez venv, bez systemu) — dla CI / Docker
install-pip:
	pip install -e ".[dev]"

# Sprawdź zależności bez instalacji
check:
	@echo "🔍  Sprawdzanie zależności..."
	@$(PYTHON) -c "import pytesseract; print('  ✅ pytesseract OK')" 2>/dev/null || echo "  ❌ pytesseract brak — uruchom: make install-system"
	@$(PYTHON) -c "import numpy"    2>/dev/null && echo "  ✅ numpy OK"    || echo "  ❌ numpy brak"
	@$(PYTHON) -c "import PIL"      2>/dev/null && echo "  ✅ Pillow OK"   || echo "  ❌ Pillow brak"
	@$(PYTHON) -c "import fastapi"  2>/dev/null && echo "  ✅ fastapi OK"  || echo "  ❌ fastapi brak"
	@$(PYTHON) -c "import mss"      2>/dev/null && echo "  ✅ mss OK"      || echo "  ❌ mss brak"
	@command -v tesseract >/dev/null 2>&1 && echo "  ✅ tesseract $(shell tesseract --version 2>&1 | head -1)" || echo "  ❌ tesseract brak — sudo apt install tesseract-ocr"
	@command -v ffmpeg    >/dev/null 2>&1 && echo "  ✅ ffmpeg OK"    || echo "  ⚠️  ffmpeg brak (opcjonalny)"

dev:
	pip install -e ".[dev]"

# Użycie
capture:
	xeen capture

server:
	xeen server

stop:
	@echo "🛑 Zamykanie serwera xeen..."
	@if pgrep -f "xeen server" >/dev/null 2>&1; then \
		pkill -TERM -f "xeen server" && sleep 2; \
		if pgrep -f "xeen server" >/dev/null 2>&1; then \
			echo "⚠️  Używam siłowego zakończenia..."; \
			pkill -KILL -f "xeen server"; \
		fi; \
		echo "✅ Serwer xeen zamknięty"; \
	else \
		echo "ℹ️  Serwer xeen nie był uruchomiony"; \
	fi

# ─── Desktop (Tauri) ──────────────────────────────────────────────────────────

install-desktop:
	@echo "🖥️  Instalacja zależności Tauri desktop..."
	@command -v cargo >/dev/null 2>&1 || { echo "❌ Brak Rust. Zainstaluj: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"; exit 1; }
	@command -v npm >/dev/null 2>&1 || { echo "❌ Brak npm/Node.js. Zainstaluj: sudo apt install nodejs npm"; exit 1; }
	@if command -v apt-get >/dev/null 2>&1; then \
		sudo apt-get install -y --no-install-recommends \
			libwebkit2gtk-4.0-dev \
			build-essential \
			curl wget \
			libssl-dev \
			libgtk-3-dev \
			libayatana-appindicator3-dev \
			librsvg2-dev; \
	fi
	cd desktop && npm install
	@echo "✅ Tauri desktop zależności zainstalowane"

desktop-dev: install-venv
	@echo "🖥️  Uruchamianie xeen desktop (dev)..."
	cd desktop && npm run dev

desktop-build: install-venv
	@echo "📦  Budowanie xeen desktop..."
	cd desktop && npm run build
	@echo "✅ Plik binarny: desktop/src-tauri/target/release/xeen-desktop"

desktop: desktop-dev

# Docker
docker:
	docker-compose build
	docker-compose up -d

docker-logs:
	docker-compose logs -f

docker-stop:
	docker-compose down

# Deploy na VPS
deploy:
	@test -n "$(DOMAIN)" || (echo "Użycie: make deploy DOMAIN=twoja-domena.pl" && exit 1)
	bash deploy.sh $(DOMAIN)

# Self-signed cert do dev
dev-certs:
	mkdir -p certs
	openssl req -x509 -nodes -days 365 \
		-newkey rsa:2048 \
		-keyout certs/privkey.pem \
		-out certs/fullchain.pem \
		-subj "/CN=localhost"

# Clean
clean:
	rm -rf dist/ build/ *.egg-info
	find . -name __pycache__ -exec rm -rf {} +
