.PHONY: install dev capture server docker deploy clean

# Lokalna instalacja
install:
	pip install -e .

dev:
	pip install -e ".[dev]"

# Użycie
capture:
	xeen capture

server:
	xeen server

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
