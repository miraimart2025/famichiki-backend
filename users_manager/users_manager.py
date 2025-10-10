from abc import ABC, abstractmethod
import json
import os

USERS_PATH = 'users_manager/users.json'

class UsersManager_abs(ABC): # ABCを継承することで抽象クラスとなる
    @abstractmethod
    def create_user(self, hashed_user_data: dict) -> None:
        pass

    @abstractmethod
    def verify_credentials(self, hashed_user_data: dict) -> bool:
        pass

class UsersManager(UsersManager_abs):
    def __init__(self, users_path: str = USERS_PATH):
        self.users_path = users_path
        self.users = self._load_users()
        self.next_id = self._get_next_id()

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
        with open(self.users_path, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=4)

    def _isexist_user(self, hashed_user_data):
        """
        store_id が既に存在するか確認する
        """
        for user in self.users.values():
            if hashed_user_data['store_id'] == user.get('store_id'):
                return True
        return False

    def create_user(self, hashed_user_data):
        """
        ユーザーを作成し、IDを割り当てて保存する
        """
        # すでに同じユーザーが存在する場合はNoneを返す
        if self._isexist_user(hashed_user_data):
            return None
        
        # 新しいユーザーIDを割り当てる
        user_id = self.next_id
        self.next_id += 1
        self.users[user_id] = hashed_user_data
        self._save()
        return hashed_user_data
    
    def verify_credentials(self, hashed_user_data):
        """
        ユーザーデータが存在するか確認する
        """
        return self._isexist_user(hashed_user_data)