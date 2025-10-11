import pytest
import os
import json
from dotenv import load_dotenv

from users_manager.users_manager import UsersManager
from services.auth_service import AuthService

load_dotenv()
TEST_USERS_PATH = "tests/test_users.json"
secret_key = os.getenv("SECRET_KEY")


@pytest.fixture
def users_manager():
    # テスト用 JSON を空に初期化
    return UsersManager(users_path=TEST_USERS_PATH)

@pytest.fixture
def auth_service(users_manager):
    return AuthService(users_manager, secret_key=secret_key)


# --- UsersManager のテスト ---

def test_create_user_and_save(users_manager):
    store_id = "abc123"
    password = "def456"

    user = users_manager.create_user(store_id, password)
    assert user.store_id == store_id
    assert user.password != password  # ハッシュ化されている

    # ファイルに保存されているか確認
    with open(users_manager.users_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data) == 1

def test_create_duplicate_user(users_manager):
    store_id = "same"
    password = "same"
    users_manager.create_user(store_id, password)
    result = users_manager.create_user(store_id, password)
    assert result is None  # 重複登録できない

def test_verify_credentials(users_manager):
    store_id = "x"
    password = "y"
    users_manager.create_user(store_id, password)
    assert users_manager.verify_credentials(store_id, password) is True
    assert users_manager.verify_credentials("no", "no") is False


# --- AuthService のテスト ---

def test_generate_and_verify_jwt(auth_service):
    token = auth_service.generate_jwt("store_1", expires_in=2)
    payload = auth_service.verify_jwt(token)
    assert payload["store_id"] == "store_1"

def test_expired_jwt(auth_service):
    token = auth_service.generate_jwt("store_2", expires_in=-1)
    assert auth_service.verify_jwt(token) is None

def test_authenticate_success(auth_service, users_manager):
    store_id = "dummy_id"
    password = "dummy"
    users_manager.create_user(store_id, password)

    token = auth_service.authenticate(store_id, password)
    assert token is not None
    payload = auth_service.verify_jwt(token)
    assert payload["store_id"] == store_id

def test_authenticate_fail(auth_service):
    token = auth_service.authenticate("not_exist", "wrong")
    assert token is None