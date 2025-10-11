from users_manager.users_manager import UsersManager
import os

# 固定ソルトは環境変数で管理
FIXED_SALT = os.getenv("FIXED_SALT")

# UsersManager 初期化
users_manager = UsersManager(fixed_salt=FIXED_SALT)

# 管理者が作りたいユーザー情報
new_users = [
    {"store_id": "store_a", "password": "pass_a"},
]

for u in new_users:
    created_user = users_manager.create_user(u["store_id"], u["password"])
    if created_user:
        print(f"作成成功: {created_user.store_id}, user_salt: {created_user.user_salt}")
    else:
        print(f"ユーザー {u['store_id']} はすでに存在します")