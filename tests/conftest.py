import pathlib, pytest
from tweet_relay.config import Config

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def real_feed() -> bytes:
    """The genuine 19-item feed for @santtiagom_, captured 2026-09-15."""
    return (FIXTURES / "santtiagom_.xml").read_bytes()


@pytest.fixture
def config(tmp_path):
    return Config(
        X_PROFILE_URL="https://x.com/santtiagom_",
        CALLMEBOT_PHONE="+34600111222",
        CALLMEBOT_APIKEY="test-key-do-not-log",
        NITTER_INSTANCES="https://m1.example.com,https://m2.example.com",
        STATE_PATH=str(tmp_path / "seen.json"),
    )
