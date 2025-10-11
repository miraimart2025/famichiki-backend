from abc import ABC, abstractmethod
import jwt
from datetime import datetime, timedelta, timezone
from users_manager.users_manager import UsersManager, UserData

class AuthService_abs(ABC):
    @abstractmethod
    def authenticate(self, store_id: str, password: str) -> dict | None:
        pass

    @abstractmethod
    def generate_jwt(self, store_id: str, expires_in: int = 3600) -> str:
        pass

    @abstractmethod
    def verify_jwt(self, token: str) -> dict | None:
        pass

class AuthService(AuthService_abs):
    def __init__(self, users_manager: UsersManager, secret_key: str = None):
        self.users_manager = users_manager
        self._SECRET_KEY = secret_key

    def authenticate(self, store_id: str, password: str) -> dict | None:
        # ユーザーが存在しない場合はNoneを返す
        if not self.users_manager.verify_credentials(store_id, password):
            return None
        # jwtを生成して返す
        return self.generate_jwt(store_id)

    def generate_jwt(self, store_id: str, expires_in: int = 3600) -> str:
        exp = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        payload = {
            "store_id": store_id,
            "exp": int(exp.timestamp())
        }
        token = jwt.encode(payload, self._SECRET_KEY, algorithm="HS256")
        return token

    def verify_jwt(self, token: str) -> dict | None:
        try:
            payload = jwt.decode(token, self._SECRET_KEY, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None