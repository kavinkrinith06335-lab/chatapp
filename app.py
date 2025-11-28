from flask import Flask, render_template, request, redirect, url_for, session, s
end_from_directory, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
import os
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'uploads'
socketio = SocketIO(app, cors_allowed_origins="*")

# Predefined users (for demo). Replace with DB-backed auth as needed.
users = {"ngt": "password1", "mar": "password2"}

# Ensure upload directory exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Initialize database with image + voice columns
def init_db():
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender TEXT,
                        recipient TEXT,
                        message TEXT,
                        image TEXT,
                        voice TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# Track online users: username -> sid
online_users = {}
# Reverse mapping sid -> username
sid_to_user = {}

@app.route('/send_message', methods=['POST'])
def send_message():
    sender = session.get('username')
    if not sender:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    recipient = request.form.get('recipient')
    message = request.form.get('message')
    image_file = request.files.get('image')
    voice_file = request.files.get('voice')

    image_url = None
    if image_file and image_file.filename:
        filename = secure_filename(str(uuid.uuid4()) + "_" + image_file.filename
)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image_file.save(filepath)
        image_url = f"/uploads/{filename}"

    voice_url = None
    if voice_file and voice_file.filename:
        filename = secure_filename(str(uuid.uuid4()) + "_" + voice_file.filename
)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        voice_file.save(filepath)
        voice_url = f"/uploads/{filename}"

    # Save message to DB
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages (sender, recipient, message, image, voi
ce) VALUES (?, ?, ?, ?, ?)",
                   (sender, recipient, message, image_url, voice_url))
    conn.commit()
    conn.close()

    msg_data = {
        'sender': sender,
        'recipient': recipient,
        'message': message,
        'image_url': image_url,
        'voice_url': voice_url,
        'timestamp': None
    }

    # Emit to both as rooms (we join users to rooms with their username)
    socketio.emit('private_message', msg_data, room=sender)
    if recipient and recipient != sender:
        socketio.emit('private_message', msg_data, room=recipient)

    return jsonify({'status': 'sent'})

@app.route('/')
def index():
    if 'username' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username] == password:
            session['username'] = username
            return redirect(url_for('chat'))
        return render_template('login.html', error="Invalid username or password
")
    return render_template('login.html')

@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('login'))
    return render_template('chat.html', users=list(users.keys()), username=sessi
on['username'])

@app.route('/logout')
def logout():
    username = session.pop('username', None)
    # remove mappings if present
    if username and username in online_users:
        sid = online_users.pop(username)
        sid_to_user.pop(sid, None)
        socketio.emit('update_users', list(online_users.keys()), broadcast=True)
    return redirect(url_for('login'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('join')
def handle_join(data):
    username = data.get('username')
    if not username:
        return

    # map username to sid and vice-versa
    online_users[username] = request.sid
    sid_to_user[request.sid] = username

    join_room(username)

    # Load last N messages involving this user (simple history)
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute("SELECT sender, recipient, message, image, voice, timestamp F
ROM messages WHERE recipient=? OR sender=? ORDER BY timestamp ASC",
                   (username, username))
    messages = cursor.fetchall()
    conn.close()

    # send history to joining user only
    history = []
    for msg in messages:
        history.append({
            'sender': msg[0],
            'recipient': msg[1],
            'message': msg[2],
            'image_url': msg[3],
            'voice_url': msg[4],
            'timestamp': msg[5]
        })

    emit('chat_history', history, room=username)

    # broadcast online users list (simple list of usernames)
    socketio.emit('update_users', list(online_users.keys()), broadcast=True)

@socketio.on('private_message')
def handle_private_message(data):
    sender = data.get('sender')
    recipient = data.get('recipient')
    message = data.get('message', '')
    image_url = data.get('image_url', None)
    voice_url = data.get('voice_url', None)

    # Save to DB (also supports messages sent via socket)
    conn = sqlite3.connect("chat.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO messages (sender, recipient, message, image, voi
ce) VALUES (?, ?, ?, ?, ?)",
                   (sender, recipient, message, image_url, voice_url))
    conn.commit()
    conn.close()

    msg_data = {
        'sender': sender,
        'recipient': recipient,
        'message': message,
        'image_url': image_url,
        'voice_url': voice_url
    }

    # deliver
    socketio.emit('private_message', msg_data, room=sender)
    if recipient and recipient != sender:
        socketio.emit('private_message', msg_data, room=recipient)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    username = sid_to_user.get(sid)
    if username:
        # cleanup
        sid_to_user.pop(sid, None)
        online_users.pop(username, None)
        socketio.emit('update_users', list(online_users.keys()), broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkze
ug=True)
