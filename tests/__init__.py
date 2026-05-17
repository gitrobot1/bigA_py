from app.config import get_settings
from app.core.database import get_db
from app.models import User as UserModel, Product as ProductModel
from app.schemas import User, Product


def test_read_users_me(.client):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}