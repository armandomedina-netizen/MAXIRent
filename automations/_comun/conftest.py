import sys
from pathlib import Path

# Agrega la carpeta del módulo común (lib) y esta carpeta (para `tests.fakes`) al path de las pruebas.
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI / "lib"))
sys.path.insert(0, str(AQUI))
