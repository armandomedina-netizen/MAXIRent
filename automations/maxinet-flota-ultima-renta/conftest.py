import sys
from pathlib import Path

# Agrega la carpeta de la automatización al path para importar maxinet_flota_ultima_renta desde las pruebas.
sys.path.insert(0, str(Path(__file__).resolve().parent))
