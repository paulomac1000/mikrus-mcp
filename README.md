# Mikr.us MCP Server

Serwer MCP (Model Context Protocol) do integracji z API [mikr.us](https://mikr.us).

## Wymagania

- Python 3.11+
- Konto i klucz API z mikr.us

## Konfiguracja

1. Sklonuj repozytorium
2. Zainstaluj zależności:
   ```bash
   pip install -e .
   ```
3. Skopiuj `.env.example` jako `.env` i uzupełnij dane:
   ```bash
   cp .env.example .env
   ```

## Uruchomienie

```bash
python -m mikrus_mcp
```

Lub bezpośrednio przez MCP:

```bash
mcp run src/mikrus_mcp/server.py
```

## Dostępne narzędzia

Serwer udostępnia narzędzia do zarządzania serwerami VPS przez API mikr.us.

## Licencja

MIT
