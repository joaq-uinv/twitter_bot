import pathlib, socket, pytest
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


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    """§5, enforced: a unit test that opens a socket fails instead of quietly calling a
    real service. Found 2026-10-21 (spec 003 T039): a dry-run test built a real bot
    from the test token and reached the live API. Tests marked `live` are exempt."""
    if request.node.get_closest_marker("live"):
        return

    def refuse(self, address, *a, **kw):
        if self.family == socket.AF_UNIX:
            return original(self, address, *a, **kw)
        self.close()          # else an unclosed-socket warning masks the real error
        raise RuntimeError(f"unit test tried to open a network connection to {address!r}")
    original = socket.socket.connect
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture(autouse=True)
def isolate_from_dotenv(monkeypatch):
    """Tests must never read the operator's real .env.

    pydantic-settings loads .env by default, so once real credentials existed the
    suite started passing them into tests that assert they are absent — a test
    failure caused purely by local configuration. Disable the file and clear the
    variables for every test.
    """
    monkeypatch.setitem(Config.model_config, "env_file", None)
    for var in ("X_PROFILE_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "STATUS_PAGE_URL", "MIRROR_LATEST_PATH",
                "NITTER_INSTANCES", "STATE_PATH", "INCLUDE_RETWEETS",
                "INCLUDE_REPLIES", "INCLUDE_QUOTES", "POLL_INTERVAL_SECONDS",
                "MAX_MESSAGES_PER_RUN", "LOG_LEVEL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def real_feed() -> bytes:
    """The genuine 19-item feed for @santtiagom_, captured 2026-09-15."""
    return (FIXTURES / "santtiagom_.xml").read_bytes()


@pytest.fixture
def config(tmp_path):
    return Config(
        X_PROFILE_URL="https://x.com/santtiagom_",
        TELEGRAM_BOT_TOKEN="123456789:TEST-token-do-not-log-AAAAAAAAAAAAAAAAAA",
        TELEGRAM_CHAT_ID="111222333",
        NITTER_INSTANCES="https://m1.example.com,https://m2.example.com",
        STATE_PATH=str(tmp_path / "seen.json"),
    )
