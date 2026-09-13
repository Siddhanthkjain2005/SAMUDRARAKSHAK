from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
DATA = ROOT / 'data'
PROCESSED = DATA / 'processed'
CACHED = DATA / 'cached'
for directory in (PROCESSED, CACHED, DATA / 'raw'):
    directory.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = Path(os.getenv('SQLITE_PATH', str(CACHED / 'samudra.sqlite3')))
AISSTREAM_API_KEY = os.getenv('AISSTREAM_API_KEY', '')
GFW_API_ACCESS_TOKEN = os.getenv('GFW_TOKEN') or os.getenv('GFW_API_ACCESS_TOKEN', '')
LLM_API_KEY = os.getenv('LLM_API_KEY', os.getenv('GROQ_API_KEY', ''))
LLM_MODEL = os.getenv('LLM_MODEL', 'llama-3.3-70b-versatile')
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', '')
LIVE_ENABLED = os.getenv('ENABLE_LIVE_AIS', 'true').lower() == 'true'
