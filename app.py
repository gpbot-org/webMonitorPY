import os
import logging
from flask import Flask, render_template, jsonify, request, redirect, url_for
from flask_login import LoginManager, login_user, login_required, logout_user, UserMixin
import pyrebase
import threading
from datetime import datetime
import requests
from time import sleep
import atexit

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'mysecretkey'  # for session management

# Firebase configuration (replace with your actual Firebase credentials)


# Initialize Firebase with Pyrebase
firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()
db = firebase.database()

# Logger setup
logging.basicConfig(level=logging.DEBUG)

# Initialize Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Models (User model is based on Firebase Authentication)
class User(UserMixin):
    def __init__(self, uid, username, email):
        self.id = uid
        self.username = username
        self.email = email

# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    user_data = db.child("users").child(user_id).get().val()
    if user_data:
        return User(uid=user_data['uid'], username=user_data['username'], email=user_data['email'])
    return None

# Routes

@app.route('/')
@login_required
def index():
    websites = db.child("websites").get().val()
    return render_template('index.html', websites=websites)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        if len(password) < 6:
            return 'Password must be at least 6 characters long.'

        try:
            # Register user using Firebase Authentication
            user = auth.create_user_with_email_and_password(email, password)
            uid = user['localId']
            user_data = {
                'uid': uid,
                'username': email.split('@')[0],  # Use part before '@' as username
                'email': email
            }
            # Save user data to Firebase
            db.child("users").child(uid).set(user_data)
            login_user(User(uid=uid, username=user_data['username'], email=email))
            return redirect(url_for('index'))  # Redirect to the homepage after successful registration
        except Exception as e:
            return f'Registration Failed. Error: {str(e)}'

    return render_template('register.html')  # Render registration page if method is GET

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            uid = user['localId']
            user_data = {
                'uid': uid,
                'username': email.split('@')[0],  # Use part before '@' as username
                'email': email
            }
            # Save user data to Firebase for session management
            db.child("users").child(uid).set(user_data)
            login_user(User(uid=uid, username=user_data['username'], email=email))
            return redirect(url_for('index'))
        except:
            return 'Login Failed. Check email or password.'

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/add_website', methods=['POST'])
@login_required
def add_website():
    url = request.json.get('url')
    if url:
        website_data = {
            'url': url,
            'timestamp': datetime.utcnow().isoformat(),
            'status': True  # Assume online initially
        }
        db.child("websites").push(website_data)
        logging.info(f'Added website: {url}')
        return jsonify({"status": "success", "message": "Website added successfully."}), 200
    return jsonify({"status": "error", "message": "URL is required."}), 400

@app.route('/delete_website', methods=['POST'])
@login_required
def delete_website():
    url = request.json.get('url')
    secret_password = request.json.get('password')
    if secret_password == os.getenv('SECRET_PASSWORD', 'supersecretpassword'):
        websites = db.child("websites").get().val()
        for website in websites:
            if websites[website]['url'] == url:
                db.child("websites").child(website).remove()
                logging.info(f'Website deleted: {url}')
                return jsonify({"status": "success", "message": "Website deleted successfully."}), 200
        return jsonify({"status": "error", "message": "Website not found."}), 404
    return jsonify({"status": "error", "message": "Invalid secret password."}), 403

@app.route('/websites', methods=['GET'])
@login_required
def get_websites():
    websites = db.child("websites").get().val()
    websites_data = [{'id': website, 'url': websites[website]['url'], 'status': websites[website]['status']} for website in websites]
    return jsonify(websites_data)

@app.route('/data')
@login_required
def get_data():
    websites = db.child("websites").get().val()
    website_status = {
        'timestamps': [website_data['timestamp'] for website_data in websites.values()],
        'statuses': [1 if website_data['status'] else 0 for website_data in websites.values()]
    }
    return jsonify(website_status)

# Function to check website status (for real-time monitoring)
def check_website_status():
    websites = db.child("websites").get().val()
    for website_id, website_data in websites.items():
        try:
            response = requests.get(website_data['url'], timeout=10)
            status = True if response.status_code == 200 else False
            if website_data['status'] != status:
                db.child("websites").child(website_id).update({'status': status, 'timestamp': datetime.utcnow().isoformat()})
        except requests.exceptions.RequestException:
            if website_data['status']:
                db.child("websites").child(website_id).update({'status': False, 'timestamp': datetime.utcnow().isoformat()})



def monitor_websites():
    while True:
        check_website_status()
        sleep(30)

# Start the periodic task on app startup using a thread
def start_monitoring():
    monitoring_thread = threading.Thread(target=monitor_websites)
    monitoring_thread.daemon = True  # Ensure it exits when the main program does
    monitoring_thread.start()

# Using atexit to start monitoring when the app is started
atexit.register(start_monitoring)

if __name__ == '__main__':
    app.run(debug=True, port=8080)
