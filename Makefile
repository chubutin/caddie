# Tareas de Caddie Virtual.  `make` solo, o `make ayuda`, lista todo.
#
# Las que borran algo piden confirmación: escribir el nombre del comando.
.DEFAULT_GOAL := ayuda
SHELL := /bin/bash
COMPOSE := docker compose

# Pide confirmación escribiendo el nombre de la tarea. $(1) = qué se va a hacer.
define confirmar
	@printf '\033[1m%s\033[0m\n' "$(1)"; \
	read -p "Escribí '$@' para confirmar: " ok; \
	[ "$$ok" = "$@" ] || { echo "Cancelado."; exit 1; }
endef

## ---------------------------------------------------------------- arranque

.PHONY: instalar
instalar:  ## Instalar dependencias y crear el .env si falta
	uv sync --extra server
	@[ -f .env ] || { cp .env.example .env; echo "Creado .env — completalo."; }

.PHONY: levantar
levantar:  ## Levantar base, API y web
	$(COMPOSE) up -d db api web
	@echo "  UI   http://localhost:$${WEB_PORT:-5173}"
	@echo "  API  http://localhost:$${API_PORT:-8010}"

.PHONY: apagar
apagar:  ## Apagar los servicios (la data queda)
	$(COMPOSE) down

.PHONY: reiniciar
reiniciar: apagar levantar  ## Apagar y volver a levantar

.PHONY: logs
logs:  ## Ver los logs en vivo
	$(COMPOSE) logs -f --tail 50

.PHONY: estado
estado:  ## Qué está corriendo y qué hay bajado
	@$(COMPOSE) ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
	@echo
	@uv run caddie status 2>/dev/null || echo "(sin data cruda todavía)"

## ------------------------------------------------------------------- datos

.PHONY: bajar
bajar:  ## Bajar de Garmin todo lo que falte (incremental)
	uv run caddie sync

.PHONY: cargar
cargar:  ## Cargar la data cruda en la base
	$(COMPOSE) run --rm etl

.PHONY: actualizar
actualizar: bajar cargar  ## Bajar de Garmin y cargar en la base

.PHONY: psql
psql:  ## Abrir una consola SQL contra la base
	$(COMPOSE) exec db psql -U $${POSTGRES_USER:-golf} -d $${POSTGRES_DB:-golf}

## ------------------------------------------------------------------ sesión

.PHONY: sesion
sesion:  ## Ver si hay sesión de Garmin abierta
	@curl -s "http://localhost:$${API_PORT:-8010}/api/auth/status?verify=true" \
	  || echo "La API no responde: ¿levantaste los servicios?"
	@echo

.PHONY: cerrar-sesion
cerrar-sesion:  ## Borrar el token de Garmin (hay que volver a entrar)
	$(call confirmar,Esto borra el token guardado. La próxima vez vas a tener que entrar de nuevo con tu contraseña.)
	@rm -rf "$$HOME/.garminconnect"
	@curl -s -X POST "http://localhost:$${API_PORT:-8010}/api/auth/logout" >/dev/null 2>&1 || true
	@echo "Sesión cerrada."

## ------------------------------------------------------------------ borrar

.PHONY: borrar-base
borrar-base:  ## Vaciar la base (la data cruda queda; se recupera con 'cargar')
	$(call confirmar,Esto borra la base. No se pierde nada: se reconstruye con 'make cargar'.)
	$(COMPOSE) down -v
	@echo "Base borrada. 'make levantar && make cargar' la reconstruye."

.PHONY: borrar-datos
borrar-datos:  ## Borrar la data cruda bajada de Garmin (hay que volver a bajarla)
	$(call confirmar,Esto borra data/raw. Para recuperarla hay que bajar TODO de Garmin otra vez — son varios minutos y muchos pedidos.)
	@rm -rf data/raw
	@mkdir -p data/raw
	@echo "Data cruda borrada."

.PHONY: borrar-todo
borrar-todo:  ## Borrar data cruda, base, token y contenedores. Deja el repo limpio.
	$(call confirmar,Esto borra TODO: data cruda, base, token de Garmin y contenedores.)
	$(COMPOSE) down -v --remove-orphans
	@rm -rf data/raw "$$HOME/.garminconnect"
	@mkdir -p data/raw
	@echo "Todo borrado. 'make instalar && make levantar && make actualizar' arranca de cero."

## -------------------------------------------------------------------- repo

.PHONY: subir
subir:  ## Revisar que no haya secretos y subir a GitHub
	@$(MAKE) --no-print-directory revisar
	@git status --porcelain | grep -q . && git status --short || echo "Nada nuevo para subir."
	@git push origin HEAD

.PHONY: revisar
revisar:  ## Buscar credenciales, tokens o data personal en el repo
	@echo "Archivos que git ignora:"
	@git status --porcelain --ignored | grep '^!!' | sed 's/^!! /  /' || true
	@echo
	@fail=0; \
	for p in '^\.env$$' '^data/' 'garmin_tokens'; do \
	  if git ls-files | grep -qE "$$p"; then echo "  !!! hay archivos que matchean $$p"; fail=1; fi; \
	done; \
	if git grep -IlE 'eyJ[A-Za-z0-9_-]{20,}' -- . >/dev/null 2>&1; then \
	  echo "  !!! parece haber un token JWT en el repo"; fail=1; fi; \
	[ $$fail -eq 0 ] && echo "  Limpio: ni .env, ni data cruda, ni tokens."

## -------------------------------------------------------------------- otros

.PHONY: ayuda
ayuda:  ## Mostrar esta lista
	@printf '\033[1mCaddie Virtual\033[0m — tareas disponibles\n\n'
	@grep -hE '^[a-zA-Z-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@printf '\nLas tareas que borran algo piden confirmación.\n'
