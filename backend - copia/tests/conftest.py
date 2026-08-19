import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    from app.services.puc_catalogo import sembrar_catalogo_puc
    sembrar_catalogo_puc(session)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def empresa_a(client):
    r = client.post("/empresas", json={"nit": "900111111", "nombre": "Empresa A SAS"})
    assert r.status_code == 201
    return r.json()


@pytest.fixture()
def empresa_b(client):
    r = client.post("/empresas", json={"nit": "900222222", "nombre": "Empresa B SAS"})
    assert r.status_code == 201
    return r.json()
