from abc import ABC, abstractmethod
import json
import os
import hashlib
from pydantic import BaseModel

USERS_PATH = 'users_manager/users.json'

class UserData(BaseModel):
    store_id: str
    password: str
    user_salt: str  

class UsersManager_abs(ABC): # ABCを継承することで抽象クラスとなる
    @abstractmethod
    def create_user(self, input_user_store_id: str, input_user_password: str) -> UserData | None:
        pass

    @abstractmethod
    def verify_credentials(self, input_user_store_id: str, input_user_password: str) -> bool:
        pass

class UsersManager(UsersManager_abs):
    def __init__(self, users_path: str = USERS_PATH, fixed_salt: str = None):
        self.users_path = users_path
        self.users = self._load_users()
        self.next_id = self._get_next_id()
        self._fixed_salt = fixed_salt or ''

    def _load_users(self) -> dict:
        """
        users_path からユーザー情報を読み込む。
        ファイルが存在しない、空、または壊れている場合は空辞書を返す。
        """
        # 空ファイルなら初期化
        if not os.path.exists(self.users_path) or os.path.getsize(self.users_path) == 0:
            print("ユーザーデータが存在しないため、初期化します。")
            return {}
        try:
            with open(self.users_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
        
    def _get_next_id(self):
        """既存ユーザーから次に割り当てるIDを決定"""
        if not self.users:
            return 1
        return max(int(uid) for uid in self.users.keys()) + 1

    def _save(self):
        """
        ユーザーデータをJSONファイルに保存する
        """
        os.makedirs(os.path.dirname(self.users_path), exist_ok=True)

        with open(self.users_path, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=4)

    def _isexist_user_by_store_id(self, user_id: str):
        """
        store_id が既に存在するか確認する
        """
        for user in self.users.values():
            if user_id == user.get('store_id'):
                return True
        return False
    
    def _hash_and_salt_password(self, password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            100_000
        ).hex()

    def create_user(self, input_user_store_id: str, input_user_password: str) -> UserData | None:
        """
        ユーザーを作成し、IDを割り当てて保存する
        """
        # すでに同じユーザーが存在する場合はNoneを返す
        if self._isexist_user_by_store_id(input_user_store_id):
            return None
        # 新しいユーザーIDを割り当てる
        user_id = self.next_id
        self.next_id += 1

        # ユーザー固有のソルトを生成
        user_salt = os.urandom(16).hex()

        # パスワードをハッシュ化して保存
        save_user_data = UserData(
            store_id=input_user_store_id,
            password=self._hash_and_salt_password(input_user_password, user_salt+self._fixed_salt),
            user_salt=user_salt
        )
        self.users[str(user_id)] = save_user_data.dict()
        self._save()
        return save_user_data

    def verify_credentials(self, input_user_store_id: str, input_user_password: str) -> bool:
        """
        ユーザーデータが存在するか確認する
        """
        for user in self.users.values():
            if input_user_store_id == user.get('store_id'):
                hashed_input_password = self._hash_and_salt_password(
                    input_user_password,
                    user.get('user_salt') + self._fixed_salt
                )
                if hashed_input_password == user.get('password'):
                    return True
        return False

   