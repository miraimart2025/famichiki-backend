import pytest
import os
from dotenv import load_dotenv
import json
import tempfile

from users_manager.users_manager import UsersManager
from services.auth_service import AuthService

load_dotenv()

# テスト用 JSON のパス
TEST_USERS_PATH = os.path.join(os.path.dirname(__file__), "test_users.json")
secret_key = os.getenv("SECRET_KEY")


@pytest.fixture
def users_manager(monkeypatch):
    return UsersManager(users_path=TEST_USERS_PATH)

@pytest.fixture
def auth_service(users_manager):
    """AuthService のインスタンス"""
    return AuthService(users_manager, secret_key=secret_key)

# --- UsersManager のテスト ---

def test_create_user_and_save(users_manager):
    hashed_user = {"store_id": "abc123", "password": "def456"}
    print(users_manager.users)
    result = users_manager.create_user(hashed_user)
    print(users_manager.users)
    assert result == hashed_user

    # ファイルに保存されているか確認
    with open(users_manager.users_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1

def test_create_duplicate_user(users_manager):
    hashed_user = {"store_id": "same", "password": "same"}
    users_manager.create_user(hashed_user)
    result = users_manager.create_user(hashed_user)
    assert result is None  # 重複登録できない

def test_verify_credentials(users_manager):
    hashed_user = {"store_id": "x", "password": "y"}
    users_manager.create_user(hashed_user)
    assert users_manager.verify_credentials(hashed_user) is True
    assert users_manager.verify_credentials({"store_id": "no", "password": "no"}) is False

# --- AuthService のテスト ---

def test_generate_and_verify_jwt(auth_service):
    token = auth_service.generate_jwt("store_1", expires_in=2)
    payload = auth_service.verify_jwt(token)
    assert payload["store_id"] == "store_1"

def test_expired_jwt(auth_service):
    token = auth_service.generate_jwt("store_2", expires_in=-1)
    assert auth_service.verify_jwt(token) is None

def test_authenticate_success(monkeypatch, auth_service):
    # 登録済みユーザーを用意
    hashed = {
        "store_id": "dummy_id",
        "password": auth_service._hash_password("dummy")
    }
    auth_service.users_manager.create_user(hashed)

    # ハッシュ化関数をモック
    monkeypatch.setattr(auth_service, "_hash_user_data", lambda s, p: hashed)

    print("Users:", auth_service.users_manager.users)

    token = auth_service.authenticate("dummy_id", "dummy")
    assert token is not None
    payload = auth_service.verify_jwt(token)
    assert payload["store_id"] == hashed["store_id"]

def test_authenticate_fail(monkeypatch, auth_service):
    # 存在しないユーザーのハッシュを返すようにする
    monkeypatch.setattr(auth_service, "_hash_user_data", lambda s, p: {
        "store_id": "nope", "password": "nope"
    })
    token = auth_service.authenticate("store", "pass")
    assert token is None