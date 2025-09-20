#!/usr/bin/env python3
"""
Multi-User Microscopy Data Upload Server
Users can select their name and upload to separate directories
"""

from flask import Flask, request, render_template_string, redirect, url_for, flash, session, jsonify, make_response, send_file
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import json
import shutil
import threading
import time
from collections import deque
import psutil

app = Flask(__name__)
app.secret_key = 'microscopy_multiuser_key_2025'

# Configuration
BASE_UPLOAD_FOLDER = 'storage'  # Change this to your base storage path
# ALLOWED_EXTENSIONS = {'tiff', 'tif', 'jpg', 'jpeg', 'png', 'nd2', 'lsm', 'czi', 'dm3', 'dm4', 'fcs'}
# Allow all file types - set to None to accept any extension
ALLOWED_EXTENSIONS = None
MAX_FILE_SIZE = 200 * 1024 * 1024 * 1024  # 200GB per file
MAX_CONCURRENT_UPLOADS = 3  # Maximum simultaneous uploads
UPLOAD_QUEUE_SIZE = 10  # Maximum queued uploads
MIN_FREE_SPACE_GB = 10  # Minimum free space to allow uploads
CHUNK_SIZE = 64 * 1024  # 64KB chunks for streaming uploads

app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Upload queue and management
upload_queue = deque()
active_uploads = {}
upload_lock = threading.Lock()

# User management file
USERS_FILE = os.path.join(BASE_UPLOAD_FOLDER, 'users.json')

# Create base directory if it doesn't exist
os.makedirs(BASE_UPLOAD_FOLDER, exist_ok=True)

def load_users():
    """Load user list from JSON file"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r') as f:
                return json.load(f)
        except:
            return []
    return []

def save_users(users):
    """Save user list to JSON file"""
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def get_user_directory(username):
    """Get user's upload directory"""
    user_dir = os.path.join(BASE_UPLOAD_FOLDER, secure_filename(username))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def allowed_file(filename):
    # If ALLOWED_EXTENSIONS is None, accept any file with a valid filename
    if ALLOWED_EXTENSIONS is None:
        return bool(filename)  # Accept any non-empty filename
    # Otherwise check against the allowed extensions
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_disk_usage():
    """Get disk usage statistics"""
    try:
        total, used, free = shutil.disk_usage(BASE_UPLOAD_FOLDER)
        return {
            'total_gb': round(total / (1024**3), 2),
            'used_gb': round(used / (1024**3), 2),
            'free_gb': round(free / (1024**3), 2),
            'used_percent': round((used / total) * 100, 1)
        }
    except:
        return {
            'total_gb': 0,
            'used_gb': 0,
            'free_gb': 0,
            'used_percent': 0
        }

def get_system_resources():
    """Get current system resource usage"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        return {
            'cpu_percent': cpu_percent,
            'memory_percent': memory.percent,
            'memory_available_gb': round(memory.available / (1024**3), 2)
        }
    except:
        return {
            'cpu_percent': 0,
            'memory_percent': 0,
            'memory_available_gb': 0
        }

def can_accept_upload():
    """Check if system can accept new uploads"""
    disk = get_disk_usage()
    if disk['free_gb'] < MIN_FREE_SPACE_GB:
        return False, f"Insufficient disk space. Only {disk['free_gb']} GB remaining."
    
    with upload_lock:
        if len(active_uploads) >= MAX_CONCURRENT_UPLOADS:
            if len(upload_queue) >= UPLOAD_QUEUE_SIZE:
                return False, "Upload queue is full. Please try again later."
            return True, "Upload will be queued."
    
    return True, "Ready to upload."

def stream_file_save(file_stream, filepath, chunk_size=CHUNK_SIZE):
    """Save file in chunks to reduce memory usage"""
    try:
        with open(filepath, 'wb') as f:
            while True:
                chunk = file_stream.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
        return True, None
    except Exception as e:
        return False, str(e)
def get_file_size_mb(filepath):
    return round(os.path.getsize(filepath) / (1024 * 1024), 2)

def get_user_folders(username):
    """Get list of folders in user's directory"""
    user_dir = get_user_directory(username)
    folders = ['']  # Empty string represents root folder
    try:
        for item in os.listdir(user_dir):
            item_path = os.path.join(user_dir, item)
            if os.path.isdir(item_path):
                folders.append(item)
    except:
        pass
    return sorted(folders)

def get_recent_files(username, folder='', limit=5):
    """Get recent files for a specific user in a specific folder"""
    user_dir = get_user_directory(username)
    if folder:
        target_dir = os.path.join(user_dir, secure_filename(folder))
    else:
        target_dir = user_dir
    
    recent_files = []
    try:
        files = os.listdir(target_dir)
        files.sort(key=lambda x: os.path.getmtime(os.path.join(target_dir, x)), reverse=True)
        
        for filename in files[:limit]:
            filepath = os.path.join(target_dir, filename)
            if os.path.isfile(filepath):
                recent_files.append({
                    'name': filename,
                    'size': get_file_size_mb(filepath),
                    'date': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M'),
                    'folder': folder
                })
    except:
        pass
    return recent_files

def get_all_user_files(username):
    """Get all files for a user across all folders"""
    user_dir = get_user_directory(username)
    all_files = []

    # Get files in root directory
    all_files.extend(get_recent_files(username, '', limit=100))

    # Get files in subdirectories
    folders = get_user_folders(username)[1:]  # Skip empty string (root)
    for folder in folders:
        all_files.extend(get_recent_files(username, folder, limit=100))

    # Sort by date, most recent first
    all_files.sort(key=lambda x: datetime.strptime(x['date'], '%Y-%m-%d %H:%M'), reverse=True)
    return all_files[:10]  # Return most recent 10 files

def get_user_file_tree(username):
    """Get complete file tree structure for a user"""
    user_dir = get_user_directory(username)
    tree = {'name': username, 'type': 'folder', 'children': []}

    try:
        # Walk through the user directory
        for root, dirs, files in os.walk(user_dir):
            rel_path = os.path.relpath(root, user_dir)

            # Handle root directory files
            if rel_path == '.':
                for file in sorted(files):
                    filepath = os.path.join(root, file)
                    tree['children'].append({
                        'name': file,
                        'type': 'file',
                        'size': get_file_size_mb(filepath),
                        'date': datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M'),
                        'path': file
                    })

                # Add subdirectories
                for dir_name in sorted(dirs):
                    dir_path = os.path.join(root, dir_name)
                    folder_node = {
                        'name': dir_name,
                        'type': 'folder',
                        'children': []
                    }

                    # Add files in this subdirectory
                    for file in sorted(os.listdir(dir_path)):
                        file_path = os.path.join(dir_path, file)
                        if os.path.isfile(file_path):
                            folder_node['children'].append({
                                'name': file,
                                'type': 'file',
                                'size': get_file_size_mb(file_path),
                                'date': datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M'),
                                'path': os.path.join(dir_name, file)
                            })

                    tree['children'].append(folder_node)
                break  # Only process first level for now
    except Exception as e:
        print(f"Error building tree for {username}: {e}")

    return tree

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <link rel="icon" type="image/png" href="/static/choanoflagellate.png">
    <link rel="shortcut icon" type="image/png" href="/static/choanoflagellate.png">
    <link rel="apple-touch-icon" href="/static/choanoflagellate.png">
    <title>King Lab Data Portal</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #8ecae6, #219ebc);
            min-height: 100vh;
            padding: 20px;
            line-height: 1.6;
        }

        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.98);
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(2, 48, 71, 0.2);
            backdrop-filter: blur(10px);
        }

        h1 {
            font-size: 2.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #023047, #219ebc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
            letter-spacing: -0.5px;
        }

        .subtitle {
            text-align: center;
            color: #023047;
            font-size: 1.1rem;
        }

        .header-container {
            margin-bottom: 30px;
            min-height: 80px;
            padding: 10px 0;
        }
        .user-section {
            background: linear-gradient(135deg, #f0fafe, #e6f7fc);
            padding: 25px;
            border-radius: 15px;
            margin: 25px 0;
            position: relative;
            overflow: hidden;
            border: 1px solid rgba(33, 158, 188, 0.1);
        }

        .user-section::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: linear-gradient(180deg, #219ebc, #023047);
        }
        .user-selection {
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
            margin-bottom: 20px;
        }
        .user-input, .user-select {
            padding: 12px 16px;
            border: 2px solid #e5e7eb;
            border-radius: 10px;
            font-size: 15px;
            transition: all 0.3s ease;
            background: white;
        }

        .user-select {
            min-width: 250px;
        }

        .user-input:focus, .user-select:focus {
            outline: none;
            border-color: #219ebc;
            box-shadow: 0 0 0 3px rgba(33, 158, 188, 0.1);
        }
        .btn {
            background: linear-gradient(135deg, #219ebc, #023047);
            color: white;
            padding: 12px 24px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 500;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(2, 48, 71, 0.3);
            letter-spacing: 0.3px;
            position: relative;
            z-index: 10;
            display: inline-block;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(2, 48, 71, 0.4);
            background: linear-gradient(135deg, #023047, #219ebc);
        }

        .btn:active {
            transform: translateY(0);
            box-shadow: 0 4px 15px rgba(2, 48, 71, 0.3);
        }

        .btn-success {
            background: linear-gradient(135deg, #ffb703, #fb8500);
            box-shadow: 0 4px 15px rgba(251, 133, 0, 0.3);
        }

        .btn-success:hover {
            background: linear-gradient(135deg, #fb8500, #ffb703);
            box-shadow: 0 6px 20px rgba(251, 133, 0, 0.4);
        }
        .current-user {
            background: linear-gradient(135deg, #e6f7fc, #d1f2fa);
            padding: 20px;
            border-radius: 12px;
            margin: 25px 0;
            border: 1px solid rgba(142, 202, 230, 0.2);
            box-shadow: 0 4px 15px rgba(142, 202, 230, 0.15);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .upload-area {
            border: 2px dashed #8ecae6;
            border-radius: 20px;
            padding: 60px 40px;
            text-align: center;
            margin: 30px 0;
            background: linear-gradient(135deg, #ffffff, #f0fafe);
            transition: all 0.3s ease;
            position: relative;
        }

        .upload-area::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, rgba(142, 202, 230, 0.05), rgba(33, 158, 188, 0.05));
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .upload-area.dragover {
            border-color: #ffb703;
            background: linear-gradient(135deg, #fffef5, #fff8e1);
        }

        .upload-icon {
            font-size: 3rem;
            margin-bottom: 15px;
        }
        .file-input {
            display: none;
        }
        .progress-container {
            margin: 20px 0;
            display: none;
        }
        .progress-bar {
            width: 100%;
            height: 25px;
            border-radius: 15px;
            background: linear-gradient(135deg, #e6f7fc, #d1f2fa);
            overflow: hidden;
            box-shadow: inset 0 2px 4px rgba(2, 48, 71, 0.06);
        }

        .progress-fill {
            height: 100%;
            background: linear-gradient(135deg, #ffb703, #fb8500);
            width: 0%;
            transition: width 0.3s ease;
            box-shadow: 0 2px 8px rgba(251, 133, 0, 0.3);
            position: relative;
            overflow: hidden;
        }

        /* Shimmer effect removed to reduce visual flash */
        .file-list {
            margin-top: 20px;
        }
        .file-item {
            padding: 15px;
            margin: 10px 0;
            background: white;
            border-radius: 10px;
            border: 1px solid #8ecae6;
            box-shadow: 0 2px 8px rgba(142, 202, 230, 0.1);
            transition: all 0.2s ease;
            position: relative;
            padding-left: 25px;
        }

        .file-item::before {
            content: '📄';
            position: absolute;
            left: 15px;
            top: 50%;
            transform: translateY(-50%);
        }

        .file-item:hover {
            box-shadow: 0 4px 12px rgba(33, 158, 188, 0.15);
            border-color: #219ebc;
            transform: translateX(5px);
        }
        .success-message {
            background: linear-gradient(135deg, #d1f2fa, #b3e8f7);
            color: #023047;
            padding: 18px 20px;
            border-radius: 12px;
            margin: 15px 0;
            border: 1px solid rgba(142, 202, 230, 0.3);
            box-shadow: 0 4px 15px rgba(142, 202, 230, 0.2);
            font-weight: 500;
        }

        .error-message {
            background: linear-gradient(135deg, #ffe5e0, #ffd4cc);
            color: #c63d00;
            padding: 18px 20px;
            border-radius: 12px;
            margin: 15px 0;
            border: 1px solid rgba(251, 133, 0, 0.2);
            box-shadow: 0 4px 15px rgba(251, 133, 0, 0.15);
            font-weight: 500;
        }
        .info-box {
            background: linear-gradient(135deg, #f0fafe, #e6f7fc);
            padding: 20px;
            border-radius: 15px;
            margin: 25px 0;
            position: relative;
            border: 1px solid rgba(142, 202, 230, 0.2);
            box-shadow: 0 4px 15px rgba(33, 158, 188, 0.1);
        }

        .info-box::before {
            content: '📊';
            position: absolute;
            top: 20px;
            right: 20px;
            font-size: 1.5rem;
            opacity: 0.5;
        }
        .stats-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin: 20px 0;
        }
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 15px;
            text-align: center;
            border: 1px solid #8ecae6;
            box-shadow: 0 4px 15px rgba(142, 202, 230, 0.1);
            transition: all 0.3s ease;
        }

        .stat-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 8px 25px rgba(33, 158, 188, 0.15);
            border-color: #219ebc;
        }

        .stat-card h4 {
            color: #334155;
            margin-bottom: 10px;
            font-size: 1.1rem;
        }

        .stat-card p {
            margin: 5px 0;
            color: #64748b;
        }

        .stat-card strong {
            color: #219ebc;
            font-size: 1.3rem;
        }
        .folder-section {
            background: linear-gradient(135deg, #fff8e1, #ffecb3);
            padding: 25px;
            border-radius: 15px;
            margin: 25px 0;
            position: relative;
            border: 1px solid rgba(255, 183, 3, 0.15);
            box-shadow: 0 4px 15px rgba(255, 183, 3, 0.08);
        }

        .folder-section::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: linear-gradient(180deg, #ffb703, #fb8500);
        }
        .folder-selection {
            display: flex;
            gap: 15px;
            align-items: center;
            flex-wrap: wrap;
            margin-bottom: 15px;
        }
        .folder-input {
            padding: 12px 16px;
            border: 2px solid #e5e7eb;
            border-radius: 10px;
            font-size: 15px;
            min-width: 250px;
            transition: all 0.3s ease;
            background: white;
        }

        .folder-input:focus {
            outline: none;
            border-color: #ffb703;
            box-shadow: 0 0 0 3px rgba(255, 183, 3, 0.1);
        }
        .current-folder {
            background: linear-gradient(135deg, #ffe5cc, #ffd4b3);
            padding: 15px;
            border-radius: 10px;
            margin: 15px 0;
            border: 1px solid rgba(251, 133, 0, 0.2);
            box-shadow: 0 2px 8px rgba(251, 133, 0, 0.1);
            font-size: 14px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .resource-section {
            background: linear-gradient(135deg, #f5fbfd, #e6f7fc);
            padding: 30px;
            border-radius: 20px;
            margin: 30px 0;
            border: 1px solid rgba(142, 202, 230, 0.15);
            box-shadow: 0 4px 15px rgba(142, 202, 230, 0.1);
        }

        .resource-section h3 {
            color: #334155;
            margin-bottom: 20px;
            font-size: 1.5rem;
        }
        .disk-usage {
            margin: 15px 0;
        }
        .usage-bar {
            width: 100%;
            height: 30px;
            background: linear-gradient(135deg, #e6f7fc, #d1f2fa);
            border-radius: 15px;
            overflow: hidden;
            position: relative;
            margin: 15px 0;
            box-shadow: inset 0 2px 4px rgba(2, 48, 71, 0.06);
        }

        .usage-fill {
            height: 100%;
            background: linear-gradient(90deg, #8ecae6 0%, #ffb703 70%, #fb8500 90%);
            transition: width 0.5s ease;
            border-radius: 15px;
            box-shadow: 0 2px 8px rgba(2, 48, 71, 0.15);
        }
        .usage-text {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-weight: bold;
            color: #333;
            text-shadow: 1px 1px 2px rgba(255,255,255,0.8);
        }
        .resource-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 15px 0;
        }
        .resource-card {
            background: white;
            padding: 20px;
            border-radius: 12px;
            text-align: center;
            border: 1px solid #8ecae6;
            box-shadow: 0 2px 8px rgba(142, 202, 230, 0.1);
            transition: all 0.3s ease;
        }

        .resource-card:hover {
            transform: translateY(-3px);
            box-shadow: 0 4px 12px rgba(33, 158, 188, 0.15);
        }

        .resource-value {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, #219ebc, #023047);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .queue-status {
            background: linear-gradient(135deg, #fff3e0, #ffe0b2);
            padding: 18px;
            border-radius: 12px;
            margin: 20px 0;
            border: 1px solid rgba(255, 183, 3, 0.2);
            box-shadow: 0 4px 15px rgba(255, 183, 3, 0.1);
            font-weight: 500;
        }

        .warning {
            background: linear-gradient(135deg, #ffe5e0, #ffd4cc);
            color: #c63d00;
            padding: 18px;
            border-radius: 12px;
            margin: 15px 0;
            border: 1px solid rgba(251, 133, 0, 0.2);
            box-shadow: 0 4px 15px rgba(251, 133, 0, 0.15);
            font-weight: 500;
        }
        .auto-refresh {
            font-size: 13px;
            color: #94a3b8;
            margin-top: 15px;
            font-style: italic;
        }

        h3 {
            color: #023047;
            font-size: 1.4rem;
            margin-bottom: 20px;
            font-weight: 600;
        }

        h4 {
            color: #219ebc;
            font-size: 1.1rem;
            margin-bottom: 10px;
            font-weight: 600;
        }

        /* Removed fade-in animation to prevent flash */

        /* Smooth scrollbar */
        ::-webkit-scrollbar {
            width: 10px;
            height: 10px;
        }

        ::-webkit-scrollbar-track {
            background: #f1f5f9;
            border-radius: 10px;
        }

        ::-webkit-scrollbar-thumb {
            background: linear-gradient(135deg, #219ebc, #023047);
            border-radius: 10px;
        }

        ::-webkit-scrollbar-thumb:hover {
            background: linear-gradient(135deg, #023047, #219ebc);
        }

        /* Loading animation for buttons */
        .btn.loading {
            position: relative;
            color: transparent;
        }

        .btn.loading::after {
            content: '';
            position: absolute;
            width: 20px;
            height: 20px;
            top: 50%;
            left: 50%;
            margin-left: -10px;
            margin-top: -10px;
            border: 2px solid white;
            border-radius: 50%;
            border-top-color: transparent;
            animation: spin 0.6s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* File tree styles */
        .file-tree-section {
            background: linear-gradient(135deg, #f5fbfd, #e6f7fc);
            padding: 30px;
            border-radius: 20px;
            margin: 30px 0;
            border: 1px solid rgba(142, 202, 230, 0.15);
            box-shadow: 0 4px 15px rgba(142, 202, 230, 0.1);
        }

        .file-tree {
            font-family: monospace;
            font-size: 14px;
            line-height: 1.8;
        }

        .tree-item {
            margin: 2px 0;
            position: relative;
        }

        .tree-folder {
            cursor: pointer;
            user-select: none;
            padding: 5px 10px;
            border-radius: 5px;
            transition: background 0.2s;
        }

        .tree-folder:hover {
            background: rgba(142, 202, 230, 0.15);
        }

        .tree-folder.collapsed > .tree-children {
            display: none;
        }

        .tree-children {
            margin-left: 20px;
            border-left: 1px solid #8ecae6;
        }

        .tree-file {
            padding: 5px 10px;
            border-radius: 5px;
            transition: background 0.2s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .tree-file:hover {
            background: rgba(142, 202, 230, 0.08);
        }

        .tree-icon {
            margin-right: 8px;
        }

        .file-actions {
            display: none;
            gap: 10px;
        }

        .tree-file:hover .file-actions {
            display: flex;
        }

        .file-action-btn {
            padding: 2px 8px;
            background: #219ebc;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
            text-decoration: none;
        }

        .file-action-btn:hover {
            background: #023047;
        }

        .file-info {
            color: #546e7a;
            font-size: 12px;
            margin-left: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header-container" style="position: relative; display: flex; align-items: center; justify-content: center;">
            <img src="/static/choanoflagellate.png" alt="King Lab" style="position: absolute; left: 0; top: 50%; transform: translateY(-50%); height: 70px; width: auto; filter: drop-shadow(0 4px 6px rgba(0,0,0,0.1));">
            <div style="text-align: center;">
                <h1 style="margin: 0;">King Lab Data Portal</h1>
                <p class="subtitle" style="margin: 5px 0 0 0;">Multi-user file management system for data uploads</p>
            </div>
        </div>
        
        <div class="info-box">
            <strong>Supported formats:</strong> TIFF, ND2, LSM, CZI, DM3, DM4, JPEG, PNG<br>
            <strong>Max file size:</strong> 200GB per file<br>
            <strong>Max concurrent uploads:</strong> {{ max_concurrent_uploads }}
        </div>

        <!-- Resource Usage Section -->
        <div class="resource-section">
            <h3>💾 System Resources</h3>
            
            <!-- Disk Usage -->
            <div class="disk-usage">
                <h4>Storage Space</h4>
                <div class="usage-bar">
                    <div class="usage-fill" style="width: {{ disk_usage.used_percent }}%"></div>
                    <div class="usage-text">{{ disk_usage.used_gb }} GB / {{ disk_usage.total_gb }} GB ({{ disk_usage.used_percent }}%)</div>
                </div>
                <p><strong>Available:</strong> {{ disk_usage.free_gb }} GB 
                {% if disk_usage.free_gb < 10 %}
                    <span style="color: #d32f2f;">⚠️ Low disk space!</span>
                {% endif %}
                </p>
            </div>

            <!-- System Resources -->
            <div class="resource-grid">
                <div class="resource-card">
                    <div class="resource-value">{{ system_resources.cpu_percent }}%</div>
                    <div>CPU Usage</div>
                </div>
                <div class="resource-card">
                    <div class="resource-value">{{ system_resources.memory_percent }}%</div>
                    <div>Memory Usage</div>
                </div>
                <div class="resource-card">
                    <div class="resource-value">{{ active_upload_count }}</div>
                    <div>Active Uploads</div>
                </div>
                <div class="resource-card">
                    <div class="resource-value">{{ queue_size }}</div>
                    <div>Queued Uploads</div>
                </div>
            </div>

            {% if queue_size > 0 %}
            <div class="queue-status">
                <strong>Upload Queue:</strong> {{ queue_size }} file(s) waiting. Average wait time: ~{{ estimated_wait_minutes }} minutes.
            </div>
            {% endif %}

            {% if not upload_allowed %}
            <div class="warning">
                <strong>⚠️ Uploads Currently Disabled:</strong> {{ upload_message }}
            </div>
            {% endif %}

            <div class="auto-refresh">
                <em>📊 Resources update every 30 seconds</em>
            </div>
        </div>

        {% with messages = get_flashed_messages() %}
            {% if messages %}
                {% for message in messages %}
                    <div class="success-message">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <!-- User Selection Section -->
        <div class="user-section">
            <h3>👤 Select User</h3>
            
            {% if not current_user %}
                <div class="user-selection">
                    <select id="existingUserSelect" class="user-select" onchange="selectExistingUser()">
                        <option value="">-- Select User --</option>
                        {% for user in users %}
                            <option value="{{ user }}">{{ user }}</option>
                        {% endfor %}
                    </select>
                </div>
            {% else %}
                <div class="current-user">
                    <strong>Current User:</strong> {{ current_user }}
                    <button class="btn" onclick="switchUser()" style="float: right;">Switch User</button>
                </div>
            {% endif %}
        </div>

        {% if current_user and upload_allowed %}
        <!-- Folder Selection Section -->
        <div class="folder-section">
            <h3>📁 Select Upload Folder</h3>
            
            <div class="folder-selection" style="display: flex; gap: 15px; align-items: center; flex-wrap: wrap;">
                <select id="folderSelect" class="folder-input" onchange="selectFolder()" style="flex: 1; min-width: 200px;">
                    <option value="">📂 Root Folder</option>
                    {% for folder in user_folders %}
                        {% if folder %}
                            <option value="{{ folder }}" {% if folder == current_folder %}selected{% endif %}>
                                📁 {{ folder }}
                            </option>
                        {% endif %}
                    {% endfor %}
                </select>

                <div style="display: flex; gap: 10px; flex: 1; min-width: 300px;">
                    <input type="text" id="newFolderName" class="folder-input" placeholder="Enter new folder name" maxlength="50" style="flex: 1;">
                    <button class="btn btn-success btn-small" onclick="createNewFolder()">Create & Select</button>
                </div>
            </div>
            
            {% if current_folder %}
                <div class="current-folder">
                    <strong>Current Upload Folder:</strong> {{ current_user }}/{{ current_folder }}
                    <button class="btn btn-small" onclick="goToRootFolder()" style="float: right;">📂 Root Folder</button>
                </div>
            {% else %}
                <div class="current-folder">
                    <strong>Current Upload Folder:</strong> {{ current_user }}/ (Root)
                </div>
            {% endif %}
        </div>

        <!-- Upload Section (only shown when user is selected and uploads allowed) -->
        <form id="uploadForm" method="POST" enctype="multipart/form-data" action="/upload">
            <!-- Always render the file input, but hide the whole upload area if conditions not met -->
            <input type="file" id="fileInput" name="files" multiple style="display: none;">

            <div class="upload-area" id="uploadArea">
                {% if upload_allowed %}
                    <div class="upload-icon">📤</div>
                    <p style="font-size: 1.2rem; font-weight: 500; color: #334155; margin-bottom: 10px;">Drag and drop files here</p>
                    <p>Files will be uploaded to: <strong>{{ current_user }}{% if current_folder %}/{{ current_folder }}{% endif %}</strong></p>
                    <button type="button" class="btn" onclick="document.getElementById('fileInput').click()">
                        Choose Files
                    </button>
                {% else %}
                    <div class="upload-icon" style="opacity: 0.5;">🚫</div>
                    <p style="font-size: 1.2rem; font-weight: 500; color: #ef4444;">Uploads temporarily disabled</p>
                    <p>{{ upload_message }}</p>
                {% endif %}
            </div>
            
            <div class="progress-container" id="progressContainer">
                <p id="progressText">Uploading...</p>
                <div class="progress-bar">
                    <div class="progress-fill" id="progressFill"></div>
                </div>
            </div>

            <div class="file-list" id="fileList"></div>

            <!-- Upload button removed - files auto-upload when selected or dropped -->
        </form>

        {% endif %}
        {% if current_user %}
        <!-- Recent Files Section (always shown for logged in users) -->
        <div style="margin-top: 30px;">
            <h3>📊 {{ current_user }}'s 10 Most Recent Uploads</h3>
            {% if recent_files %}
                {% for file in recent_files %}
                    <div class="file-item">
                        <strong>{{ file.name }}</strong>
                        {% if file.folder %}
                            <span style="color: #666;"> (in folder: {{ file.folder }})</span>
                        {% endif %}
                        <br>
                        <small>{{ file.size }} MB - Uploaded: {{ file.date }}</small>
                    </div>
                {% endfor %}
            {% else %}
                <p style="color: #666; font-style: italic;">No files uploaded yet.</p>
            {% endif %}
        </div>
        {% endif %}

        <!-- File Tree Section -->
        {% if users %}
        <div class="file-tree-section">
            <h3>📂 File Browser</h3>
            <div style="background: linear-gradient(135deg, #f0f9ff, #e0f2fe); padding: 15px; border-radius: 10px; margin-bottom: 20px; border: 1px solid rgba(59, 130, 246, 0.15);">
                <strong style="color: #1e40af; font-size: 16px;">📊 Total Storage Usage:</strong>
                <span style="color: #334155; font-size: 16px; margin-left: 10px;">
                    <strong>{{ total_stats.file_count }}</strong> files •
                    <strong>{{ total_stats.total_size_mb }}</strong> MB
                    {% if total_stats.total_size_gb %}
                        ({{ total_stats.total_size_gb }} GB)
                    {% endif %}
                </span>
            </div>
            <p style="color: #666; font-size: 14px; margin-bottom: 20px;">Click on folders to expand/collapse. Hover over files to see actions.</p>
            <div class="file-tree">
                {% for user in users %}
                    <div class="tree-item">
                        <div class="tree-folder collapsed" onclick="toggleFolder(this)">
                            <span class="tree-icon">📁</span>
                            <strong>{{ user }}</strong>
                            <span class="file-info">({{ user_stats[user].file_count }} files, {{ user_stats[user].total_size_mb }} MB)</span>
                        </div>
                        <div class="tree-children" id="tree-{{ user }}" style="display: none;">
                            <!-- Content will be loaded dynamically -->
                        </div>
                    </div>
                {% endfor %}
            </div>
        </div>
        {% endif %}
    </div>

    <script>
        // Restore scroll position after page load
        window.addEventListener('load', function() {
            const scrollPos = sessionStorage.getItem('scrollPosition');
            if (scrollPos) {
                window.scrollTo(0, parseInt(scrollPos));
                sessionStorage.removeItem('scrollPosition');
            }
        });

        // Save scroll position before any navigation
        function saveScrollPosition() {
            sessionStorage.setItem('scrollPosition', window.scrollY);
        }

        // Function to trigger file input
        function openFilePicker() {
            console.log('openFilePicker called');
            var fileInput = document.getElementById('fileInput');
            if (fileInput) {
                console.log('File input found, triggering click');
                fileInput.click();
            } else {
                console.error('File input not found');
            }
        }

        // Wait for DOM to be ready
        document.addEventListener('DOMContentLoaded', function() {
            console.log('DOM loaded - initializing event handlers');

            // Add fallback click handler for label if needed
            var labels = document.querySelectorAll('label[for="fileInput"]');
            labels.forEach(function(label) {
                label.addEventListener('click', function(e) {
                    console.log('Label clicked');
                    // Let the default label behavior work, but log it
                });
            });

            // Add event listeners for optional elements
            const newUserInput = document.getElementById('newUserName');
            if (newUserInput) {
                newUserInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        createNewUser();
                    }
                });
            }

            const newFolderInput = document.getElementById('newFolderName');
            if (newFolderInput) {
                newFolderInput.addEventListener('keypress', function(e) {
                    if (e.key === 'Enter') {
                        createNewFolder();
                    }
                });
            }
        });

        function selectExistingUser() {
            const select = document.getElementById('existingUserSelect');
            const username = select.value;
            if (username) {
                saveScrollPosition();
                window.location.href = '/set_user/' + encodeURIComponent(username);
            }
            // No alert when empty - user just hasn't selected yet
        }

        function createNewUser() {
            const input = document.getElementById('newUserName');
            const username = input.value.trim();
            if (username) {
                if (username.length > 50) {
                    alert('Username must be 50 characters or less');
                    return;
                }
                saveScrollPosition();
                window.location.href = '/set_user/' + encodeURIComponent(username);
            } else {
                alert('Please enter a username');
            }
        }

        function switchUser() {
            saveScrollPosition();
            window.location.href = '/switch_user';
        }

        function selectFolder() {
            const select = document.getElementById('folderSelect');
            const folderName = select.value;
            const currentUser = '{{ current_user }}';
            saveScrollPosition();
            window.location.href = '/set_folder/' + encodeURIComponent(currentUser) + '/' + encodeURIComponent(folderName);
        }

        function createNewFolder() {
            const input = document.getElementById('newFolderName');
            const folderName = input.value.trim();
            if (folderName) {
                if (folderName.length > 50) {
                    alert('Folder name must be 50 characters or less');
                    return;
                }
                if (!/^[a-zA-Z0-9_\\-\\s.]+$/.test(folderName)) {
                    alert('Folder name can only contain letters, numbers, spaces, dots, hyphens, and underscores');
                    return;
                }
                const currentUser = '{{ current_user }}';
                saveScrollPosition();
                window.location.href = '/set_folder/' + encodeURIComponent(currentUser) + '/' + encodeURIComponent(folderName);
            } else {
                alert('Please enter a folder name');
            }
        }

        function goToRootFolder() {
            const currentUser = '{{ current_user }}';
            saveScrollPosition();
            window.location.href = '/set_folder/' + encodeURIComponent(currentUser) + '/';
        }

        // File tree functions
        function toggleFolder(element) {
            element.classList.toggle('collapsed');
            const username = element.querySelector('strong').textContent;
            const childrenDiv = document.getElementById('tree-' + username);

            if (!element.classList.contains('collapsed')) {
                // Load files if not already loaded
                if (!childrenDiv.dataset.loaded) {
                    loadUserFiles(username, childrenDiv);
                }
                childrenDiv.style.display = 'block';
                element.querySelector('.tree-icon').textContent = '📂';
            } else {
                childrenDiv.style.display = 'none';
                element.querySelector('.tree-icon').textContent = '📁';
            }
        }

        function loadUserFiles(username, container) {
            container.innerHTML = '<div style="padding: 10px;">Loading...</div>';

            // Fetch user files via API
            fetch('/api/user-files/' + encodeURIComponent(username))
                .then(response => response.json())
                .then(data => {
                    container.innerHTML = '';
                    container.dataset.loaded = 'true';
                    renderFileTree(data, container, username);
                })
                .catch(error => {
                    container.innerHTML = '<div style="padding: 10px; color: red;">Error loading files</div>';
                    console.error('Error loading files:', error);
                });
        }

        function renderFileTree(tree, container, username) {
            if (tree.children && tree.children.length > 0) {
                tree.children.forEach(item => {
                    if (item.type === 'folder') {
                        // Render folder
                        const folderDiv = document.createElement('div');
                        folderDiv.className = 'tree-item';
                        folderDiv.innerHTML = `
                            <div class="tree-folder collapsed" onclick="toggleSubfolder(this)">
                                <span class="tree-icon">📁</span>
                                ${item.name}
                                <span class="file-info">(${item.children ? item.children.length : 0} files)</span>
                            </div>
                            <div class="tree-children" style="display: none;">
                                ${renderFiles(item.children, username)}
                            </div>
                        `;
                        container.appendChild(folderDiv);
                    } else {
                        // Render file
                        const fileDiv = document.createElement('div');
                        fileDiv.className = 'tree-file';
                        fileDiv.innerHTML = `
                            <div>
                                <span class="tree-icon">📄</span>
                                ${item.name}
                                <span class="file-info">${item.size} MB - ${item.date}</span>
                            </div>
                            <div class="file-actions">
                                <a href="/preview/${username}/${item.path}" target="_blank" class="file-action-btn">Preview</a>
                                <a href="/download/${username}/${item.path}" class="file-action-btn">Download</a>
                            </div>
                        `;
                        container.appendChild(fileDiv);
                    }
                });
            } else {
                container.innerHTML = '<div style="padding: 10px; color: #666;">No files uploaded yet</div>';
            }
        }

        function renderFiles(files, username) {
            if (!files || files.length === 0) return '<div style="padding: 10px; color: #666;">Empty folder</div>';

            return files.map(file => `
                <div class="tree-file">
                    <div>
                        <span class="tree-icon">📄</span>
                        ${file.name}
                        <span class="file-info">${file.size} MB - ${file.date}</span>
                    </div>
                    <div class="file-actions">
                        <a href="/preview/${username}/${file.path}" target="_blank" class="file-action-btn">Preview</a>
                        <a href="/download/${username}/${file.path}" class="file-action-btn">Download</a>
                    </div>
                </div>
            `).join('');
        }

        function toggleSubfolder(element) {
            element.classList.toggle('collapsed');
            const childrenDiv = element.nextElementSibling;

            if (!element.classList.contains('collapsed')) {
                childrenDiv.style.display = 'block';
                element.querySelector('.tree-icon').textContent = '📂';
            } else {
                childrenDiv.style.display = 'none';
                element.querySelector('.tree-icon').textContent = '📁';
            }
        }

        // Event listeners are now added in DOMContentLoaded above

        {% if current_user %}
        // File upload functionality
        document.addEventListener('DOMContentLoaded', function() {
            const uploadArea = document.getElementById('uploadArea');
            const fileInput = document.getElementById('fileInput');
            const fileList = document.getElementById('fileList');
            const progressContainer = document.getElementById('progressContainer');
            const progressFill = document.getElementById('progressFill');
            const progressText = document.getElementById('progressText');

            if (!uploadArea || !fileInput) {
                console.error('Upload elements not found');
                return;
            }

            uploadArea.addEventListener('dragover', (e) => {
                e.preventDefault();
                uploadArea.classList.add('dragover');
            });

            uploadArea.addEventListener('dragleave', () => {
                uploadArea.classList.remove('dragover');
            });

            uploadArea.addEventListener('drop', (e) => {
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                fileInput.files = e.dataTransfer.files;
                updateFileList();
            });

            fileInput.addEventListener('change', updateFileList);

            function updateFileList() {
                fileList.innerHTML = '';

                if (fileInput.files.length > 0) {

                    Array.from(fileInput.files).forEach(file => {
                        const fileItem = document.createElement('div');
                        fileItem.className = 'file-item';
                        fileItem.innerHTML = `
                            <strong>${file.name}</strong><br>
                            <small>${(file.size / (1024 * 1024)).toFixed(2)} MB</small>
                        `;
                        fileList.appendChild(fileItem);
                    });

                    // Auto-submit the form after files are selected
                    console.log('Auto-uploading files...');
                    submitForm();
                }
            }

            function submitForm() {
                if (fileInput.files.length === 0) {
                    return;
                }

                const formData = new FormData();
                Array.from(fileInput.files).forEach(file => {
                    formData.append('files', file);
                });

                progressContainer.style.display = 'block';
                progressText.textContent = 'Starting upload...';

                const xhr = new XMLHttpRequest();

                xhr.upload.addEventListener('progress', function(e) {
                    if (e.lengthComputable) {
                        const percentComplete = (e.loaded / e.total) * 100;
                        progressFill.style.width = percentComplete + '%';
                        progressText.textContent = `Uploading... ${Math.round(percentComplete)}%`;
                    }
                });

                xhr.addEventListener('load', function() {
                    if (xhr.status === 200) {
                        progressText.textContent = 'Upload complete! Refreshing page...';
                        saveScrollPosition();
                        setTimeout(() => location.reload(), 2000);
                    } else {
                        progressText.textContent = 'Upload failed. Please try again.';
                        // Clear the file input so user can try again
                        fileInput.value = '';
                        fileList.innerHTML = '';
                    }
                });

                xhr.addEventListener('error', function() {
                    progressText.textContent = 'Upload failed. Please try again.';
                    // Clear the file input so user can try again
                    fileInput.value = '';
                    fileList.innerHTML = '';
                });

                xhr.open('POST', '/upload');
                xhr.send(formData);
            }

            // Still handle manual form submit if needed
            document.getElementById('uploadForm').addEventListener('submit', function(e) {
                e.preventDefault();
                submitForm();
            });
    }); // Close DOMContentLoaded for file upload functionality
        // Auto-refresh resource data every 30 seconds
        setInterval(function() {
            fetch('/api/resources')
                .then(response => response.json())
                .then(data => {
                    // Update disk usage
                    document.querySelector('.usage-fill').style.width = data.disk_usage.used_percent + '%';
                    document.querySelector('.usage-text').textContent = 
                        data.disk_usage.used_gb + ' GB / ' + data.disk_usage.total_gb + ' GB (' + data.disk_usage.used_percent + '%)';
                    
                    // Update resource cards
                    const resourceValues = document.querySelectorAll('.resource-value');
                    if (resourceValues.length >= 4) {
                        resourceValues[0].textContent = data.system_resources.cpu_percent + '%';
                        resourceValues[1].textContent = data.system_resources.memory_percent + '%';
                        resourceValues[2].textContent = data.active_upload_count;
                        resourceValues[3].textContent = data.queue_size;
                    }
                })
                .catch(error => console.log('Resource update failed:', error));
        }, 30000); // Close the setInterval
        {% endif %}
    </script>
</body>
</html>
'''

@app.route('/')
def index():
    # Get server IP address
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        server_ip = s.getsockname()[0]
        s.close()
    except:
        server_ip = "localhost"

    users = load_users()
    current_user = session.get('current_user')
    current_folder = session.get('current_folder', '')
    user_folders = []
    recent_files = []
    
    # Get resource information
    disk_usage = get_disk_usage()
    system_resources = get_system_resources()
    upload_allowed, upload_message = can_accept_upload()
    
    with upload_lock:
        active_upload_count = len(active_uploads)
        queue_size = len(upload_queue)
    
    # Estimate wait time (rough calculation)
    estimated_wait_minutes = max(1, queue_size * 2)  # Assume 2 minutes per queued upload
    
    if current_user:
        user_folders = get_user_folders(current_user)
        recent_files = get_all_user_files(current_user)
    
    # Get user statistics
    user_stats = {}
    total_files_all = 0
    total_size_all = 0

    for user in users:
        user_dir = get_user_directory(user)
        try:
            files = [f for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f))]
            # Also count files in subdirectories
            for item in os.listdir(user_dir):
                item_path = os.path.join(user_dir, item)
                if os.path.isdir(item_path):
                    subfiles = [f for f in os.listdir(item_path) if os.path.isfile(os.path.join(item_path, f))]
                    files.extend(subfiles)

            total_size = sum(os.path.getsize(os.path.join(user_dir, f)) for f in os.listdir(user_dir) if os.path.isfile(os.path.join(user_dir, f)))
            # Add size from subdirectories
            for item in os.listdir(user_dir):
                item_path = os.path.join(user_dir, item)
                if os.path.isdir(item_path):
                    for subfile in os.listdir(item_path):
                        subfile_path = os.path.join(item_path, subfile)
                        if os.path.isfile(subfile_path):
                            total_size += os.path.getsize(subfile_path)

            user_stats[user] = {
                'file_count': len(files),
                'total_size_mb': round(total_size / (1024 * 1024), 1)
            }
            total_files_all += len(files)
            total_size_all += total_size
        except:
            user_stats[user] = {'file_count': 0, 'total_size_mb': 0}

    # Calculate total statistics
    total_stats = {
        'file_count': total_files_all,
        'total_size_mb': round(total_size_all / (1024 * 1024), 1),
        'total_size_gb': round(total_size_all / (1024 * 1024 * 1024), 2) if total_size_all > (1024 * 1024 * 1024) else None
    }

    response = make_response(render_template_string(HTML_TEMPLATE,
                                server_ip=server_ip,
                                users=users,
                                current_user=current_user,
                                current_folder=current_folder,
                                user_folders=user_folders,
                                recent_files=recent_files,
                                user_stats=user_stats,
                                total_stats=total_stats,
                                disk_usage=disk_usage,
                                system_resources=system_resources,
                                upload_allowed=upload_allowed,
                                upload_message=upload_message,
                                active_upload_count=active_upload_count,
                                queue_size=queue_size,
                                estimated_wait_minutes=estimated_wait_minutes,
                                max_concurrent_uploads=MAX_CONCURRENT_UPLOADS))

    # Add cache-busting headers
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/static/<path:filename>')
def serve_static(filename):
    """Serve static files like images"""
    if filename == 'choanoflagellate.png':
        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'choanoflagellate.png')
        if os.path.exists(file_path):
            return send_file(file_path, mimetype='image/png')
        else:
            print(f"File not found at: {file_path}")
    return 'File not found', 404

@app.route('/api/resources')
def api_resources():
    """API endpoint for resource updates"""
    disk_usage = get_disk_usage()
    system_resources = get_system_resources()

    with upload_lock:
        active_upload_count = len(active_uploads)
        queue_size = len(upload_queue)

    return jsonify({
        'disk_usage': disk_usage,
        'system_resources': system_resources,
        'active_upload_count': active_upload_count,
        'queue_size': queue_size
    })

@app.route('/api/user-files/<username>')
def api_user_files(username):
    """API endpoint to get user file tree"""
    tree = get_user_file_tree(username)
    return jsonify(tree)

@app.route('/download/<username>/<path:filepath>')
def download_file(username, filepath):
    """Download a specific file"""
    user_dir = get_user_directory(username)
    file_path = os.path.join(user_dir, filepath)

    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        flash('File not found')
        return redirect(url_for('index'))

@app.route('/preview/<username>/<path:filepath>')
def preview_file(username, filepath):
    """Preview a file (mainly for images)"""
    user_dir = get_user_directory(username)
    file_path = os.path.join(user_dir, filepath)

    if os.path.exists(file_path) and os.path.isfile(file_path):
        # Check if it's an image file
        ext = filepath.rsplit('.', 1)[1].lower() if '.' in filepath else ''
        if ext in {'jpg', 'jpeg', 'png', 'tiff', 'tif'}:
            return send_file(file_path, mimetype=f'image/{ext}')
        else:
            # For non-image files, download instead
            return send_file(file_path, as_attachment=True)
    else:
        return 'File not found', 404

@app.route('/set_user/<username>')
def set_user(username):
    username = secure_filename(username)
    if not username:
        flash('Invalid username')
        return redirect(url_for('index'))
    
    # Add user to list if not exists
    users = load_users()
    if username not in users:
        users.append(username)
        save_users(users)
    
    # Set current user in session
    session['current_user'] = username
    
    # Create user directory
    get_user_directory(username)
    
    flash(f'Selected user: {username}')
    return redirect(url_for('index'))

@app.route('/set_folder/<username>/<path:folder>')
@app.route('/set_folder/<username>/')
def set_folder(username, folder=''):
    if session.get('current_user') != username:
        flash('Please select the user first')
        return redirect(url_for('index'))
    
    # Clean folder name
    if folder:
        folder = secure_filename(folder)
        if folder:
            # Create the folder if it doesn't exist
            user_dir = get_user_directory(username)
            folder_path = os.path.join(user_dir, folder)
            os.makedirs(folder_path, exist_ok=True)
    
    session['current_folder'] = folder
    
    if folder:
        flash(f'Selected folder: {username}/{folder}')
    else:
        flash(f'Selected root folder for: {username}')
    
    return redirect(url_for('index'))

@app.route('/switch_user')
def switch_user():
    session.pop('current_user', None)
    session.pop('current_folder', None)
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_files():
    current_user = session.get('current_user')
    current_folder = session.get('current_folder', '')
    
    if not current_user:
        flash('Please select a user first')
        return redirect(url_for('index'))
    
    # Check if uploads are allowed
    upload_allowed, upload_message = can_accept_upload()
    if not upload_allowed and "queue" not in upload_message.lower():
        flash(f'Upload failed: {upload_message}')
        return redirect(url_for('index'))
    
    uploaded_files = []
    failed_files = []
    user_dir = get_user_directory(current_user)
    
    # Determine target directory
    if current_folder:
        target_dir = os.path.join(user_dir, secure_filename(current_folder))
        os.makedirs(target_dir, exist_ok=True)
    else:
        target_dir = user_dir
    
    if 'files' not in request.files:
        flash('No files selected')
        return redirect(url_for('index'))
    
    files = request.files.getlist('files')
    
    for file in files:
        if file and file.filename:
            if allowed_file(file.filename):
                # Create filename with timestamp
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{timestamp}_{secure_filename(file.filename)}"
                filepath = os.path.join(target_dir, filename)
                
                try:
                    # Use streaming save to reduce memory usage
                    success, error = stream_file_save(file.stream, filepath)
                    
                    if success:
                        file_size = get_file_size_mb(filepath)
                        uploaded_files.append(f"{file.filename} ({file_size} MB)")
                    else:
                        failed_files.append(f"{file.filename}: {error}")
                        # Clean up partial file
                        if os.path.exists(filepath):
                            os.remove(filepath)
                            
                except Exception as e:
                    failed_files.append(f"{file.filename}: {str(e)}")
                    if os.path.exists(filepath):
                        os.remove(filepath)
            else:
                failed_files.append(f"{file.filename}: File type not allowed")
    
    # Flash results
    if uploaded_files:
        folder_text = f"/{current_folder}" if current_folder else ""
        flash(f'✅ Successfully uploaded {len(uploaded_files)} file(s) to {current_user}{folder_text}')
    
    if failed_files:
        for failed in failed_files[:3]:  # Show first 3 failures
            flash(f'❌ {failed}')
        if len(failed_files) > 3:
            flash(f'❌ ...and {len(failed_files) - 3} more failed uploads')
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    print(f"Starting Multi-User Microscopy Upload Server...")
    print(f"Base upload folder: {BASE_UPLOAD_FOLDER}")
    print(f"Access the server at: http://[your-server-ip]:748")
    if ALLOWED_EXTENSIONS:
        print(f"Supported file types: {', '.join(ALLOWED_EXTENSIONS)}")
    else:
        print("All file types are supported")
    
    app.run(host='0.0.0.0', port=748, debug=True)
