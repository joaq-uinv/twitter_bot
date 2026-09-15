import pathlib, pytest
from hypothesis import settings as hyp_settings
from hypothesis.database import DirectoryBasedExampleDatabase
from tweet_relay.config import Config

# The container may run as the host uid so the state bind-mount is writable (plan
# A-4.1), which leaves /app unwritable for the image user. Hypothesis defaults its
# example database to /app/.hypothesis and warns when it cannot write there — and
# pyproject promotes warnings to errors, so that warning fails the suite.
hyp_settings.register_profile(
    "container", database=DirectoryBasedExampleDatabase("/tmp/.hypothesis"))
hyp_settings.load_profile("container")

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
