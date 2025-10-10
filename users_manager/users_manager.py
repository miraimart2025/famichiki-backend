from abc import ABC, abstractmethod
import json
import os

USERS_PATH = 'users.json'

class UsersManager_abs(ABC): # ABCを継承することで抽象クラスとなる
    @abstractmethod
    def create_user(self, hashed_user_data: dict) -> None:
        pass

    @abstractmethod
    def verify_credentials(self, hashed_user_data: dict) -> bool:
        pass

class UsersManager(UsersManager_abs):
    def __init__(self):
        self.users = json.load(open(USERS_PATH, 'r')) if os.path.exists(USERS_PATH) else {}
        self.next_id = max(self.users.keys(), default=0) + 1

    def _save(self):
        """
        ユーザーデータをJSONファイルに保存する
        """
        with open(USERS_PATH, 'w', encoding='utf-8') as f:
            json.dump(self.users, f, ensure_ascii=False, indent=4)

    def _isexist_user(self, hashed_user_data):
        """
        同じユーザーが存在するか確認する
        """
        for user in self.users.values():
            if hashed_user_data == user:
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