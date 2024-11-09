# routes.py
from flask import render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from app import app, db, login_manager
from models import User, HealthRecord ,Department 
from forms import LoginForm, AddEmployeeForm, EmployeeForm
from datetime import datetime, timedelta
import json, re
from sqlalchemy.exc import IntegrityError
import pytz 


# 日本語部門名取得関数を定義
def get_japanese_department_name(department_abbreviation):
    """略称から日本語の部署名を取得"""
    department = Department.query.filter_by(abbreviation=department_abbreviation).first()
    return department.name if department else '不明な部署'

# 権限チェック関数の定義
def check_admin_permission():
    """管理者権限を確認し、なければアクセスを拒否する"""
    if not current_user.is_admin:
        flash("このページにアクセスする権限がありません。", 'error')
        return redirect(url_for('index'))
    return None  # 管理者の場合は何もしない

def get_last_registered_employee():
    # 最新の社員をIDで取得
    return User.query.order_by(User.id.desc()).first()

# ユーザー情報の読み込み
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def validate_password(password):
    if 4 <= len(password) <= 16 and any(c.islower() for c in password) and any(c.isdigit() for c in password):
        return True
    return False

# ログインページのルート
@app.route("/", methods=["GET", "POST"])
def login(): 
    form = LoginForm()
    if form.validate_on_submit():
        employee_number = form.employee_number.data
        password = form.password.data
        user = User.query.filter_by(employee_number=employee_number).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))
        else:
            flash("無効な社員番号またはパスワードです。", "danger")
    return render_template("login_form.html", form=form)


# ログアウトのルート
@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("ログアウトしました")
    return redirect(url_for("login"))

# トップページのルート
@app.route('/index')
@login_required
def index():
    return render_template('index.html')

# 健康登録ページのルート
@app.route('/health')
@login_required
def register_health():
    return render_template('register_health.html')

# 健康結果ページのルート
@app.route('/health_result', methods=['POST'])
@login_required  
def health_result():
    temperature = request.form.get('temperature')
    if not temperature:
        flash("体温を入力してください。")
        return redirect(url_for('register_health'))
    
    throat = request.form.get('throat')
    fever = request.form.get('fever')
    cough = request.form.get('cough')
    selected_parts_json = request.form.get('selectedParts')  # JSON 形式で取得

    # JSON 文字列をリストに変換
    selected_parts = json.loads(selected_parts_json) if selected_parts_json else []
    selected_parts_sum = ", ".join(selected_parts)  # リストを文字列に変換

    # 健康記録をデータベースに保存
    new_record = HealthRecord(
        user_id=current_user.id,
        temperature=temperature,
        throat=throat,
        fever=fever,
        cough=cough,
        selected_parts=selected_parts_sum
    )
    
    db.session.add(new_record)
    db.session.commit()

    # 結果データをセッションに保存し、リダイレクト
    session['result_data'] = {
        'temperature': temperature,
        'throat': '正常' if throat == "normal" else '痛い',
        'fever': '正常' if fever == "normal" else '高い',
        'cough': 'ない' if cough == "no" else 'ある',
        'selected_parts': 'なし' if selected_parts_sum == "" else selected_parts_sum,
    }
    return redirect(url_for('display_health_result'))

@app.route('/display_health_result')
@login_required
def display_health_result():
    result_data = session.get('result_data', {})
    return render_template('health_result.html', result_data=result_data)


# 社員情報閲覧ページのルート
@app.route("/view_employee", methods=["GET"])
@login_required
def view_employee():
    check_result = check_admin_permission()  # 権限チェック
    if check_result:
        return check_result  # アクセス拒否の場合はリダイレクト

    query = request.args.get('query', '').strip()
    employees = User.query.filter(
        (User.employee_number.like(f'%{query}%')) |
        (User.name.like(f'%{query}%')) |
        (User.department.like(f'%{query}%'))
    ).all()
    
    if not employees:
        flash('指定された社員は見つかりませんでした。', 'info')  # 検索結果が空の場合にメッセージを表示

    for employee in employees:
        # 日本語の部署名を取得して追加
        employee.department_name_jp = get_japanese_department_name(employee.department)

    today = datetime.now()  # Get the current date
    return render_template('view_employee.html', employees=employees, today=today)



# 特定の社員の体温データAPIのルート
@app.route('/api/employee/<int:user_id>/temperature_data', methods=['GET'])
@login_required
def get_employee_temperature_data(user_id):
    if current_user.id != user_id and not current_user.is_admin:
        return jsonify({"error": "Unauthorized access"}), 403

    # 現在の日時を取得し、明後日の日付を計算
    end_date = datetime.now(pytz.utc) + timedelta(days=1)  # 明後日
    start_date = end_date - timedelta(days=7)  # 明後日から過去7日間

    period = request.args.get('period', '1w')
    if period == '2w':
        start_date = end_date - timedelta(weeks=2)
    elif period == '1m':
        start_date = end_date - timedelta(days=30)
    elif period == '3m':
        start_date = end_date - timedelta(weeks=12)
    elif period == '1y':
        start_date = end_date - timedelta(weeks=52)

    jst = pytz.timezone('Asia/Tokyo')
    start_date_jst = start_date.astimezone(jst)
    end_date_jst = end_date.astimezone(jst)

    # 指定した期間の体温データを取得
    records = HealthRecord.query.filter(
        HealthRecord.user_id == user_id,
        HealthRecord.date >= start_date,
        HealthRecord.date <= end_date
    ).order_by(HealthRecord.date).all()
    labels = []
    current_date = start_date_jst

    while current_date <= end_date_jst:
        labels.append(current_date.strftime('%Y-%m-%d'))
        current_date += timedelta(days=1)

    data = [record.temperature for record in records]
    jst_dates = [record.date.astimezone(jst).strftime('%Y-%m-%d') for record in records]

    # 各日付の平均温度を計算
    average_temperatures = {}
    all_records = HealthRecord.query.filter(
        HealthRecord.date >= start_date,
        HealthRecord.date <= end_date
    ).all()

    for record in all_records:
        date_str = record.date.astimezone(jst).strftime('%Y-%m-%d')
        if date_str not in average_temperatures:
            average_temperatures[date_str] = []
        average_temperatures[date_str].append(float(record.temperature))

    average_data = [
        sum(average_temperatures[date]) / len(average_temperatures[date]) if date in average_temperatures else None
        for date in labels
    ]

    # 体温データをラベルに関連付け
    data_jst = []

    for label in labels:
        if label in jst_dates:
            index = jst_dates.index(label)
            data_jst.append(data[index])
        else:
            data_jst.append(None)  # データがない場合はNoneを追加

    return jsonify({'labels': labels, 'data': data_jst, 'average': average_data})



# 特定の社員の健康記録を取得するAPIのルート
@app.route('/api/health_record', methods=['GET'])
def get_health_record():
    user_id = request.args.get('user_id')  
    start = request.args.get('start')
    end = request.args.get('end')
    jst = pytz.timezone('Asia/Tokyo')

    # start と end を日本時間 (JST) から UTC に変換
    start_dt_jst = datetime.strptime(start, '%Y-%m-%dT%H:%M:%S.%fZ')
    end_dt_jst = datetime.strptime(end, '%Y-%m-%dT%H:%M:%S.%fZ')

    start_dt_utc = jst.localize(start_dt_jst).astimezone(pytz.utc)
    end_dt_utc = jst.localize(end_dt_jst).astimezone(pytz.utc)
    
    health_records = HealthRecord.query.filter(
        HealthRecord.user_id == user_id,
        HealthRecord.date >= start_dt_utc,
        HealthRecord.date <= end_dt_utc
    ).all()

    
    if health_records:
        throat_jp = "ない" if health_records[0].throat == "normal" else "痛い"
        fever_jp = "ない" if health_records[0].fever == "normal" else "高い"
        cough_jp = "ない" if health_records[0].cough == "no" else "ある"
        
        # selected_partsが空の場合は'なし'と表示
        selected_parts_jp = 'なし' if not health_records[0].selected_parts else health_records[0].selected_parts
        
        return jsonify({
            'temperature': health_records[0].temperature,
            'throat': throat_jp,
            'fever': fever_jp,
            'cough': cough_jp,
            'selected_parts': selected_parts_jp,
            'date': health_records[0].date.strftime('%Y-%m-%d')  # 日付を追加
        })
    else:
        return jsonify({}), 404



# 管理者画面のルート
@app.route("/admin")
@login_required
def admin():
    # 総社員数を取得
    total_employees = User.query.count()
    # 管理者の総数を取得
    total_admins = User.query.filter_by(is_admin=True).count()

    return render_template('admin.html', total_employees=total_employees, total_admins=total_admins)


# 社員登録ページのルート
@app.route("/add_employee", methods=["GET", "POST"])
@login_required
def add_employee():
    check_result = check_admin_permission()  # 権限チェック
    if check_result:
        return check_result  # アクセス拒否の場合はリダイレクト

    form = AddEmployeeForm()

    if form.validate_on_submit():
        new_password = form.password.data
        employee_number = form.employee_number.data
        email = form.email.data
        is_admin = form.is_admin.data

        # メールアドレスの重複を確認
        existing_employee = User.query.filter_by(email=email).first()
        if existing_employee:
            form.email.errors.append('このメールアドレスはすでに使用されています。')
            return render_template('add_employee.html', form=form)

        # 社員作成　DBインサート
        new_employee = User(
            employee_number=employee_number,
            department=form.department.data,
            name=form.name.data,
            phone=form.phone.data,
            email=email,
            is_admin=is_admin
        )
        new_employee.set_password(new_password)
        db.session.add(new_employee)

        # 日本語の部署名を取得
        department = Department.query.filter_by(abbreviation=new_employee.department).first()
        department_name_jp = department.name if department else new_employee.department

        try:
            db.session.commit()
            flash('社員が正常に登録されました。', 'success')

            # 成功した場合は結果ページにリダイレクト
            return render_template(
                'add_employee_result.html', 
                employee=new_employee,
                department_name_jp=department_name_jp,
                employee_name=new_employee.name,
                is_admin="あり" if new_employee.is_admin else "なし"
            )
        except IntegrityError:
            db.session.rollback()  # Roll back the session on error
            form.email.errors.append('登録中にエラーが発生しました。社員番号、メールアドレス、または電話番号が重複している可能性があります。')

    # Check for form errors and flash them
    return render_template('add_employee.html', form=form)



# 社員削除ページのルート
@app.route('/delete_employee', methods=['GET', 'POST'])
@login_required
def delete_employee():
    check_result = check_admin_permission()  # 権限チェック
    if check_result:
        return check_result  # アクセス拒否の場合はリダイレクト

    employee = None  # 初期値として None を設定
    department_name_jp = None  # 日本語の部署名も初期化
    employee_name = None  # 社員名も初期化

    if request.method == 'POST':
        action = request.form.get('action')
        employee_number = request.form.get('employee_number')
        employee = User.query.filter_by(employee_number=employee_number).first()

        if not employee:
            flash('指定された社員番号は見つかりませんでした。', 'error')
            return redirect(url_for('delete_employee'))  # フォームを再表示

        # 日本語の部署名を取得
        department = Department.query.filter_by(abbreviation=employee.department).first()
        department_name_jp = department.name if department else employee.department
        employee_name = employee.name  # 社員名を取得

        if action == 'delete':
            # 削除処理を実行
            db.session.delete(employee)
            db.session.commit()

            # 削除結果ページにリダイレクト
            return render_template(
                'delete_employee_result.html', 
                employee_number=employee_number, 
                department_name_jp=department_name_jp,
                employee_name=employee_name  # 社員名も渡す
            )
    
    # GET リクエストの場合、またはPOSTで検索した社員情報を表示
    return render_template('delete_employee.html', employee=employee, department_name_jp=department_name_jp)


# 特定の社員の体温グラフページのルート
# 一般ユーザーは自分のみ
@app.route('/employee/<int:employee_id>/graph', methods=['GET'])
@login_required
def employee_graph(employee_id):
    if not current_user.is_admin and current_user.id != employee_id:
        flash("このグラフにアクセスする権限がありません。", "error")
        return redirect(url_for('view_employee'))  # Redirect to employee view if unauthorized

    employee = User.query.get_or_404(employee_id)
    return render_template('graph.html', employee=employee)


# 基本情報変更ページのルート
@app.route('/change_info/<int:employee_id>', methods=['GET', 'POST'])
@login_required
def change_info(employee_id):
    form = EmployeeForm()

    form.department.choices = [
        ('hr', '人事部'),
        ('it', 'IT部門'),
        ('sales', '営業部'),
        ('marketing', 'マーケティング部'),
        ('finance', '財務部')
    ]

    employee = User.query.get(employee_id)
    check_result = check_admin_permission()  # 権限チェック
    if check_result:
        return check_result  # アクセス拒否の場合はリダイレクト

    if request.method == 'POST' and form.validate_on_submit():
        employee.employee_number = form.employee_id.data
        employee.department = form.department.data
        employee.name = form.name.data
        employee.phone = form.phone.data
        employee.email = form.email.data
        employee.is_admin = form.admin_rights.data  # 管理者権限の更新

        try:
            db.session.commit()
            
            # 部署名を取得
            department_name = Department.query.filter_by(abbreviation=employee.department).first()
            
            if department_name:
                department_name = department_name.name
            else:
                department_name = '不明な部署'
            
            return render_template('change_info_result.html', employee=employee, department_name=department_name)

        except Exception as e:
            db.session.rollback()
            app.logger.error(f'情報の更新中にエラーが発生しました: {e}')
            flash('情報の更新中にエラーが発生しました。再試行してください。', 'danger')
            return redirect(url_for('change_info', employee_id=employee.id))

    form.employee_id.data = employee.employee_number
    form.department.data = employee.department
    form.name.data = employee.name
    form.phone.data = employee.phone
    form.email.data = employee.email
    form.admin_rights.data = employee.is_admin  # 管理者権限の初期値を設定

    return render_template('change_info.html', form=form)



#パスワード変更のルート
@app.route('/change_password/<int:employee_id>', methods=['GET', 'POST'])
@login_required
def change_password(employee_id):
    employee = User.query.get(employee_id)
    if employee is None:
        flash('社員が見つかりません。', 'danger')
        return redirect(url_for('view_employee'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        # パスワードの長さを確認
        if len(new_password) < 4 or len(new_password) > 16:
            flash('パスワードは4文字以上16文字以下である必要があります。', 'danger')
            return redirect(url_for('change_password', employee_id=employee_id))

        # 小文字と数字が含まれているか確認
        if not re.search(r'[a-z]', new_password) or not re.search(r'[0-9]', new_password):
            flash('パスワードには少なくとも1つの小文字と1つの数字を含める必要があります。', 'danger')
            return redirect(url_for('change_password', employee_id=employee_id))

        # パスワードの一致を確認
        if new_password != confirm_password:
            flash('新しいパスワードと確認用パスワードが一致しません。', 'danger')
            return redirect(url_for('change_password', employee_id=employee_id))

        # パスワードを設定
        employee.set_password(new_password)  # ここでパスワードをハッシュ化することを確認してください
        db.session.commit()

        return redirect(url_for('change_password_result'))  # 結果ページにリダイレクト

    return render_template('change_password.html', employee=employee)


# パスワード変更結果ページのルート
@app.route('/change_password/result')
@login_required
def change_password_result():
    return render_template('change_password_result.html')

# 基本情報変更ページのルート
@app.route("/update_employee_info", methods=["GET", "POST"])
@login_required
def update_employee_info():
    check_result = check_admin_permission()  # 権限チェック
    if check_result:
        return check_result  # アクセス拒否の場合はリダイレクト

    employee_to_update = None
    if request.method == 'POST':
        employee_number = request.form.get('employee_number')
        employee_to_update = User.query.filter_by(employee_number=employee_number).first()

        
        if employee_to_update:
            return redirect(url_for('change_info', employee_id=employee_to_update.id))
        else:
            flash('指定された社員番号は見つかりませんでした。', 'error')

    return render_template('update_employee_info.html', employee=employee_to_update)

# 404エラーのハンドリング
@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

# 401エラーのハンドリング
@app.errorhandler(401)
def unauthorized_error(error):
    flash("認証に失敗しました。ログイン画面に戻ります。", "error")
    return redirect(url_for('login'))