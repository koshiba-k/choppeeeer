# create_user.py
from app import app, db  # app.pyのFlaskアプリケーションとデータベースをインポート
from models import User  # Userモデルのインポート
import getpass

# アプリケーションコンテキスト内で作業する
with app.app_context():
    print("ユーザー作成")
    password = input("パスワード: ")
    employee_number = input("社員番号: ")
    department = input("部署: ")
    name = input("氏名: ")
    phone = input("電話番号: ")
    email = input("メールアドレス: ")
    
    # 管理者権限の選択
    is_admin_input = input("管理者権限を持つユーザーですか？ (y/n): ")
    is_admin = True if is_admin_input.lower() == 'y' else False

    # 新しいユーザーを作成し、データベースに追加
    new_user = User(
        employee_number=employee_number,
        department=department,
        name=name,
        phone=phone,
        email=email,
        is_admin=is_admin
    )
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    print(f"{'管理者' if is_admin else '一般'}ユーザー「{name}」を作成しました。")