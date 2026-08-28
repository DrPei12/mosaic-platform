import sys
from pathlib import Path

from _pytest.config import Config

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def pytest_configure(config: Config) -> None:
    marker = "minio: tests requiring a local MinIO-compatible S3 service"
    if marker not in config.getini("markers"):
        config.addinivalue_line("markers", marker)
