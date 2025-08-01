from flask import Flask, request, send_from_directory, render_template, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import os
import zipfile
from io import BytesIO
from werkzeug.utils import secure_filename

app = Flask(__name__)
# 检查是否在Vercel环境中
is_vercel = os.environ.get('VERCEL') == '1'

# 在Vercel环境中使用/tmp目录进行临时存储
app.config['UPLOAD_FOLDER'] = '/tmp/uploads' if is_vercel else 'uploads'
# Vercel有文件大小限制，调整为更合理的值
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 if is_vercel else 64 * 1024 * 1024 * 1024  # Vercel限制为50MB，本地为64GB
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a_very_secret_key_replace_with_your_own') # 从环境变量获取Secret Key

# 确保模板和静态文件路径正确
app.template_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app.static_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')

socketio = SocketIO(app, async_mode='threading')

online_users = {}

# 确保上传文件夹存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    files = os.listdir(app.config['UPLOAD_FOLDER'])
    # 检查用户是否已设置昵称
    if 'nickname' not in session:
        return redirect(url_for('nickname_setup'))

    return render_template('index.html', files=files)

@app.route('/nickname_setup', methods=['GET', 'POST'])
def nickname_setup():
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        if nickname:
            if len(nickname) > 20:
                return render_template('nickname_input.html', error='昵称长度不能超过20个字符。')
            # 检查昵称是否已被占用
            used_nicknames = [user['nickname'] for user in online_users.values()]
            if nickname in used_nicknames:
                return render_template('nickname_input.html', error='昵称已被占用，请换一个昵称。')
            session['nickname'] = nickname # 将昵称存储在session中
            # 此时SocketIO连接可能还未建立，昵称会在connect事件中同步
            return redirect(url_for('index'))
        else:
            return render_template('nickname_input.html', error='昵称不能为空。')

    return render_template('nickname_input.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files[]' not in request.files:
        return '没有文件被上传', 400

    files = request.files.getlist('files[]')
    
    # 检查是否是文件夹上传（通过文件名是否包含路径分隔符）
    is_folder_upload = any(os.sep in f.filename or '/' in f.filename for f in files)

    if is_folder_upload:
        # 文件夹上传逻辑
        # 假设所有文件都属于同一个顶级文件夹
        top_folder_name = "unknown_folder"
        if files and (os.sep in files[0].filename or '/' in files[0].filename):
            top_folder_name = files[0].filename.split(os.sep)[0].split('/')[0]
        
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, False) as zipf:
            for file_item in files:
                # 使用原始的相对路径作为压缩包内的路径
                zipf.writestr(file_item.filename, file_item.read())
        
        zip_buffer.seek(0)
        
        # 生成安全的zip文件名
        zip_filename = secure_filename(top_folder_name + '.zip')
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
        
        try:
            with open(save_path, 'wb') as f:
                f.write(zip_buffer.read())
            return '文件夹上传并压缩成功', 200
        except Exception as e:
            return f'文件夹上传失败: {e}', 500
    else:
        # 单个文件上传逻辑
        uploaded_count = 0
        for file in files:
            if file.filename == '':
                continue  # 跳过空文件名
            if file:
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                try:
                    file.save(save_path)
                    uploaded_count += 1
                except Exception as e:
                    print(f"保存文件 {filename} 失败: {e}") # 记录错误，但不中断其他文件上传
        
        if uploaded_count > 0:
            return '文件上传成功', 200
        else:
            return '没有有效文件被上传', 400

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=True)

// 添加favicon处理路由
@app.route('/favicon.ico')
@app.route('/favicon.png')
def handle_favicon():
    # 返回空响应，状态码204表示无内容
    return '', 204

@socketio.on('connect')
def handle_connect():
    print('Client connected: ', request.sid)

    # 从session中获取昵称，如果没有则使用匿名用户
    user_nickname = session.get('nickname', '匿名用户')
    online_users[request.sid] = {'nickname': user_nickname, 'sid': request.sid}
    print(f'User {user_nickname} connected with sid {request.sid}')

    # 广播更新后的用户列表
    users_to_broadcast = list(online_users.values())
    emit('update_users', users_to_broadcast, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected: ', request.sid)

    if request.sid in online_users:
        del online_users[request.sid]
    # 广播更新后的用户列表
    users_to_broadcast = list(online_users.values())
    emit('update_users', users_to_broadcast, broadcast=True)

@socketio.on('set_nickname')
def handle_set_nickname(data):
    # 这个事件现在主要用于已连接的客户端更新SocketIO的在线用户列表，
    # 实际昵称设置应通过nickname_setup页面完成并存储在session中。
    # 也可以允许在这里修改当前session的昵称，并同步到session。

    nickname = data.get('nickname', '匿名用户').strip()
    if not nickname:
        return
    
    print(f'Client {request.sid} updated nickname to {nickname}')
    if request.sid in online_users:
        online_users[request.sid]['nickname'] = nickname
        session['nickname'] = nickname # 同步到session

        # 广播更新后的用户列表
        users_to_broadcast = list(online_users.values())
        emit('update_users', users_to_broadcast, broadcast=True)

@socketio.on('send_message')
def handle_send_message(data):
    text = data.get('text')
    recipient_sid = data.get('recipient_sid')
    
    if text and request.sid in online_users:
        nickname = online_users[request.sid].get('nickname', '匿名用户')
        message_data = {
            'nickname': nickname,
            'text': text,
            'sender_sid': request.sid
        }
        
        if recipient_sid and recipient_sid in online_users:
            # 私信
            print(f'Received private message from {nickname} to {online_users[recipient_sid]["nickname"]}: {text}')
            message_data['recipient_sid'] = recipient_sid
            # 将消息发送给发送者和接收者
            emit('new_message', message_data, room=request.sid)
            emit('new_message', message_data, room=recipient_sid)
        else:
            # 公聊
            print(f'Received public message from {nickname}: {text}')
            # 广播消息给所有连接的客户端
            emit('new_message', message_data, broadcast=True)

if __name__ == '__main__':
    # 本地开发时使用
    socketio.run(app, host='0.0.0.0', port=19999, debug=True)
else:
    # 用于Vercel部署
    # 注意：在Vercel环境中，WebSocket可能不完全支持，
    # 可能需要使用长轮询或其他替代方案
    app = app  # 这是一个占位语句，确保else块有内容