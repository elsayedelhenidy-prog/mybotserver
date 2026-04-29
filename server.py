"""
🤖 ADSPOWER BOT DASHBOARD SERVER
================================
- Real-time bot status (GREEN/RED dots)
- Login credentials management
- Send commands to all bots
- Railway deployment ready
"""

from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import json
import time
import os
from datetime import datetime
from threading import Lock

app = Flask(__name__)
CORS(app)

# ═══════════════════════════════════════════════════════════════════════════════
# 📦 DATA STORAGE (In-memory + File backup)
# ═══════════════════════════════════════════════════════════════════════════════

DATA_FILE = "bot_data.json"
data_lock = Lock()

# Bot statuses: {bot_id: {status, last_seen, rdp_name, ip, current_task, ...}}
bots = {}

# Login credentials queue: [{email, password, recovery_email, assigned_to, status}]
login_queue = []

# Pending commands: {bot_id: [commands]}
pending_commands = {}

def load_data():
    """Load saved data from file."""
    global bots, login_queue
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                bots = data.get('bots', {})
                login_queue = data.get('login_queue', [])
    except:
        pass

def save_data():
    """Save data to file."""
    try:
        with data_lock:
            with open(DATA_FILE, 'w') as f:
                json.dump({
                    'bots': bots,
                    'login_queue': login_queue
                }, f, indent=2)
    except:
        pass

# Load on startup
load_data()

# ═══════════════════════════════════════════════════════════════════════════════
# 🌐 DASHBOARD ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def dashboard():
    """Main dashboard page."""
    return render_template('dashboard.html')

@app.route('/api/status')
def get_status():
    """Get all bot statuses."""
    current_time = time.time()
    
    # Update status based on last_seen (offline if not seen in 30 seconds)
    bots_to_remove = []
    for bot_id, bot in bots.items():
        last_seen = bot.get('last_seen', 0)
        if current_time - last_seen > 300:  # Remove if offline for 5+ minutes
            bots_to_remove.append(bot_id)
        elif current_time - last_seen > 30:
            bot['status'] = 'offline'
        elif current_time - last_seen > 10:
            bot['status'] = 'idle'
    
    # Remove old offline bots
    for bot_id in bots_to_remove:
        del bots[bot_id]
    
    if bots_to_remove:
        save_data()
    
    return jsonify({
        'bots': bots,
        'login_queue': login_queue,
        'timestamp': current_time
    })

@app.route('/api/logins', methods=['POST'])
def add_logins():
    """Add login credentials (bulk)."""
    data = request.json
    logins_text = data.get('logins', '')
    
    added = 0
    for line in logins_text.strip().split('\n'):
        line = line.strip()
        if '|' in line:
            parts = line.split('|')
            if len(parts) >= 2:
                login_entry = {
                    'email': parts[0].strip(),
                    'password': parts[1].strip(),
                    'recovery_email': parts[2].strip() if len(parts) > 2 else '',
                    'assigned_to': None,
                    'status': 'pending',
                    'added_at': time.time()
                }
                login_queue.append(login_entry)
                added += 1
    
    save_data()
    return jsonify({'success': True, 'added': added})

@app.route('/api/send_logins', methods=['POST'])
def send_logins_to_bots():
    """Send login credentials to all online bots."""
    online_bots = [bid for bid, b in bots.items() if b.get('status') in ['online', 'idle']]
    pending_logins = [l for l in login_queue if l.get('status') == 'pending']
    
    assigned = 0
    for i, bot_id in enumerate(online_bots):
        if i < len(pending_logins):
            login = pending_logins[i]
            login['assigned_to'] = bot_id
            login['status'] = 'assigned'
            
            # Add command to pending
            if bot_id not in pending_commands:
                pending_commands[bot_id] = []
            
            pending_commands[bot_id].append({
                'type': 'login',
                'email': login['email'],
                'password': login['password'],
                'recovery_email': login['recovery_email'],
                'timestamp': time.time()
            })
            assigned += 1
    
    save_data()
    return jsonify({'success': True, 'assigned': assigned, 'online_bots': len(online_bots)})

@app.route('/api/clear_logins', methods=['POST'])
def clear_logins():
    """Clear all login credentials."""
    global login_queue
    login_queue = []
    save_data()
    return jsonify({'success': True})

# ═══════════════════════════════════════════════════════════════════════════════
# 🤖 BOT API ROUTES (Called by bots on RDPs)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/bot/heartbeat', methods=['POST'])
def bot_heartbeat():
    """Bot sends heartbeat to report status."""
    data = request.json
    bot_id = data.get('bot_id', 'unknown')
    
    bots[bot_id] = {
        'status': data.get('status', 'online'),
        'last_seen': time.time(),
        'rdp_name': data.get('rdp_name', bot_id),
        'ip': request.remote_addr,
        'current_task': data.get('current_task', 'idle'),
        'tasks_completed': data.get('tasks_completed', 0),
        'adspower_logged_in': data.get('adspower_logged_in', False),
        'version': data.get('version', '1.0')
    }
    
    save_data()
    
    # Check if there are pending commands for this bot
    commands = pending_commands.pop(bot_id, [])
    
    return jsonify({
        'success': True,
        'commands': commands,
        'server_time': time.time()
    })

@app.route('/bot/login_result', methods=['POST'])
def bot_login_result():
    """Bot reports login result."""
    data = request.json
    bot_id = data.get('bot_id', 'unknown')
    success = data.get('success', False)
    email = data.get('email', '')
    message = data.get('message', '')
    
    # Update login queue status
    for login in login_queue:
        if login.get('email') == email:
            login['status'] = 'success' if success else 'failed'
            login['result_message'] = message
            login['completed_at'] = time.time()
            break
    
    # Update bot status
    if bot_id in bots:
        bots[bot_id]['adspower_logged_in'] = success
        bots[bot_id]['last_login_result'] = {
            'success': success,
            'email': email,
            'message': message,
            'timestamp': time.time()
        }
    
    save_data()
    return jsonify({'success': True})

@app.route('/bot/get_otp', methods=['POST'])
def get_otp_from_guerrilla():
    """Fetch OTP from Guerrilla Mail for a specific email."""
    data = request.json
    email = data.get('email', '')
    
    if not email:
        return jsonify({'success': False, 'error': 'No email provided'})
    
    # Extract email parts
    email_parts = email.split('@')
    if len(email_parts) != 2:
        return jsonify({'success': False, 'error': 'Invalid email format'})
    
    email_user = email_parts[0]
    
    try:
        import urllib.request
        
        # Guerrilla Mail API
        # Set email address
        set_url = f"https://api.guerrillamail.com/ajax.php?f=set_email_user&email_user={email_user}"
        req = urllib.request.Request(set_url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        
        # Check inbox
        check_url = "https://api.guerrillamail.com/ajax.php?f=check_email&seq=0"
        req2 = urllib.request.Request(check_url, headers={'User-Agent': 'Mozilla/5.0'})
        resp2 = urllib.request.urlopen(req2, timeout=10)
        inbox_data = json.loads(resp2.read().decode('utf-8'))
        
        # Look for OTP in recent emails
        emails = inbox_data.get('list', [])
        for email_item in emails[:5]:  # Check last 5 emails
            subject = email_item.get('mail_subject', '').lower()
            if 'otp' in subject or 'verification' in subject or 'code' in subject or 'adspower' in subject:
                # Get email body
                mail_id = email_item.get('mail_id')
                body_url = f"https://api.guerrillamail.com/ajax.php?f=fetch_email&email_id={mail_id}"
                req3 = urllib.request.Request(body_url, headers={'User-Agent': 'Mozilla/5.0'})
                resp3 = urllib.request.urlopen(req3, timeout=10)
                email_data = json.loads(resp3.read().decode('utf-8'))
                
                body = email_data.get('mail_body', '')
                
                # Extract OTP (usually 4-6 digits)
                import re
                otp_match = re.search(r'\b(\d{4,6})\b', body)
                if otp_match:
                    return jsonify({
                        'success': True,
                        'otp': otp_match.group(1),
                        'subject': email_item.get('mail_subject', '')
                    })
        
        return jsonify({'success': False, 'error': 'No OTP found in emails'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ═══════════════════════════════════════════════════════════════════════════════
# 🚀 SERVER START
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
