import os
import sys

# Same import convention as gui/app.py: the project root (pytcad/) must
# be importable so `gui` and `pytcad` resolve however this is launched.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend_service.server import serve  # noqa: E402

if __name__ == "__main__":
    sys.exit(serve())
