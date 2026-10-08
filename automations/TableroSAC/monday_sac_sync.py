"""Punto de entrada de la sincronización monday -> Google Sheets del tablero de tickets de SAC
(una pestaña por grupo del tablero)."""
from sac_sync.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
