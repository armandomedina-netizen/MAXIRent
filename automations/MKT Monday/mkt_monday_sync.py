"""Punto de entrada de la sincronización monday -> hoja MKT; la lógica vive en el paquete mkt_sync."""
import sys

from mkt_sync.cli import main

if __name__ == "__main__":
    sys.exit(main())
