import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("AUTH_MODE", "mock")
os.environ.setdefault("ALLOW_MOCK_AUTH", "true")
os.environ.setdefault("AUTH_SECRET", "test-auth-secret")
