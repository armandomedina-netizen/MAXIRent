import sys
from pathlib import Path

# Agrega la carpeta de la automatización al path para importar sac_sync desde las pruebas.
sys.path.insert(0, str(Path(__file__).resolve().parent))
