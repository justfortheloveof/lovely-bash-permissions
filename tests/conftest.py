import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture
def devin_global_config_dir(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point DEVIN_GLOBAL_CONFIG_DIR at a random temp dir.

    Prevents tests from reading or destroying the real ~/.config/devin/config.json.
    """
    with tempfile.TemporaryDirectory(prefix="devin-global-") as tmp:
        monkeypatch.setenv("DEVIN_GLOBAL_CONFIG_DIR", tmp)
        yield tmp
