"""Umumiy sozlamalar va papkalar."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_LIST = RAW / "list"      # ro'yxat sahifalari (page_001.html ...)
RAW_DOCS = RAW / "docs"      # hujjat matni HTML (<lex_id>.html)
RAW_CARDS = RAW / "cards"    # "Asosiy rekvizitlar" kartochkasi HTML
CLEAN = DATA / "clean"
STATE = DATA / "state"       # checkpoint, xatolar logi
INDEX_DIR = DATA / "index"

LIST_INDEX = STATE / "list_index.jsonl"   # ro'yxatdagi barcha hujjatlar
FAILURES = STATE / "failures.jsonl"
CHUNKS = DATA / "chunks.jsonl"
METADATA_CSV = DATA / "metadata.csv"
REPORT = ROOT / "report.md"

BASE = "https://lex.uz"
# Yig'iladigan to'plamlar. lang=4 -> o'zbek (lotin).
#   qonun  - bosh sahifadagi "Milliy bazadagi hujjatlar -> Qonunlar (1 588)" havolasi, form_id=3968
#   kodeks - kodekslar (Mehnat, Fuqarolik, Soliq ...), form_id=3964; "Qonunlar" soniga kirmaydi
#   konstitutsiya - form_id=4131
COLLECTIONS = {
    "qonun": {"url": f"{BASE}/uz/search/nat?lang=4&sort_id=3975&form_id=3968", "expected": 1588},
    "kodeks": {"url": f"{BASE}/uz/search/nat?lang=4&sort_id=3975&form_id=3964", "expected": 28},
    # 2023-yilgi amaldagi va 1992-yilgi (amalda emas) Konstitutsiya
    "konstitutsiya": {"url": f"{BASE}/uz/search/nat?lang=4&sort_id=3975&form_id=4131", "expected": 2},
}
LIST_URL = COLLECTIONS["qonun"]["url"]
DOC_URL = BASE + "/uz/docs/{lex_id}"
CARD_URL = BASE + "/uz/actinfo/card1/{lex_id}"
EXPECTED_TOTAL = sum(c["expected"] for c in COLLECTIONS.values())
PAGE_SIZE = 20

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DELAY_RANGE = (1.0, 2.0)   # har so'rov orasidagi pauza, soniya
MAX_RETRIES = 6
TIMEOUT = 90

# Chunking
TOKENIZER_NAME = "BAAI/bge-m3"
CHUNK_MAX_TOKENS = 800
CHUNK_TARGET_MIN = 300
CHUNK_OVERLAP_TOKENS = 80

for p in (RAW_LIST, RAW_DOCS, RAW_CARDS, CLEAN, STATE, INDEX_DIR):
    p.mkdir(parents=True, exist_ok=True)
