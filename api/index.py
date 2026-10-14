# Vercel이 실행하는 입구 파일이에요. 실제 앱은 app/main.py 에 있어요.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402,F401
