from abc import ABC, abstractmethod
import hashlib
import json
import os

class UsersManager_abs(ABC): # ABCを継承することで抽象クラスとなる
    @abstractmethod
    def create_user(self, user_data: dict) -> None:
        pass

    @abstractmethod
    def check_user(self, user_id: int) -> dict | None:
        pass

    @abstractmethod
    def update_user(self, user_id: int, user_data: dict) -> dict | None:
        pass

    @abstractmethod
    def delete_user(self, user_id: int) -> dict | None:
        pass


class UsersManager(UsersManager_abs):
    def __init__(self, path='users.json'):
        self.users = json.load(open(path, 'r')) if os.path.exists(path) else {}
        self.next_id = max(self.users.keys(), default=0) + 1

    def create_user(self, user_data):
        """
        ユーザーを作成し、IDを割り当てて保存する
        """
        # すでに同じユーザーが存在する場合はNoneを返す
        if self._isexist_user(user_data):
            return None
        
        # 新しいユーザーIDを割り当てる
        user_id = self.next_id
        self.next_id += 1
        user_data_hashed = self._hash_user_data(user_data)
        self.users[user_id] = user_data_hashed

        return user_data

    def get_user(self, user_id):
        """
        指定されたIDのユーザー情報を取得する
        """
        return self.users.get(user_id)

    def update_user(self, user_id, user_data):
        """
        指定されたIDのユーザー情報を更新する
        """
        if user_id in self.users.keys():
            if 'password' in user_data:
                user_data['password'] = self._hash_password(user_data['password'])
            self.users[user_id].update(user_data)
            return self.users[user_id]
        return None

    def delete_user(self, user_id):
        """
        指定されたIDのユーザー情報を削除する
        """
        return self.users.pop(user_id, None)

    def _hash_store_id(self, store_id):
        """
        store_idをSHA-256でハッシュ化する
        """
        return hashlib.sha256(store_id.encode()).hexdigest()

    def _hash_password(self, password):
        """
        passwordをSHA-256でハッシュ化する
        """
        return hashlib.sha256(password.encode()).hexdigest()

    def _hash_user_data(self, user_data):
        """
        user_dataをSHA-256でハッシュ化する
        """
        user_data_hashed = user_data.copy()
        user_data_hashed['store_id'] = self._hash_store_id(user_data['store_id'])
        user_data_hashed['password'] = self._hash_password(user_data['password'])
        return user_data_hashed
    
    def _isexist_user(self, user_data):
        """
        同じユーザーが存在するか確認する
        """
        user_data_hashed = self._hash_user_data(user_data)
        for user in self.users.values():
            if user_data_hashed == user:
                return True
        return False