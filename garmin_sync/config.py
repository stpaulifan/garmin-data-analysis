from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "garmin.db"
FIT_DIR = DATA_DIR / "fit"
# Der API-Key liegt außerhalb des Repos (SDK-Standard):
#   ~/.config/garmin/connect-personal-api-key   (chmod 600)
# alternativ Umgebungsvariable GARMIN_PERSONAL_API_KEY.
