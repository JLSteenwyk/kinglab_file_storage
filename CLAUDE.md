# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based multi-user microscopy data upload server that allows researchers to upload large microscopy image files to separate user directories. The system includes upload queuing, resource monitoring, and supports various microscopy file formats.

## Development Commands

### Running the Server
```bash
# Activate virtual environment
source venv/bin/activate

# Run the server (default port 748)
python microscopy_upload_server.py

# The server will be accessible at http://localhost:748
```

### Installing Dependencies
```bash
# Create virtual environment if needed
python3 -m venv venv
source venv/bin/activate

# Install required packages
pip install flask werkzeug psutil
```

## Architecture

### Core Components

1. **Flask Application** (`microscopy_upload_server.py`)
   - Multi-user session management with username selection
   - File upload handling with chunked streaming for large files
   - Upload queue management with concurrent upload limits
   - Resource monitoring (CPU, memory, disk usage)
   - REST API endpoints for resource status

2. **Storage Structure**
   - Base directory: `microscopy_storage/`
   - User directories: `microscopy_storage/<username>/`
   - User folders: `microscopy_storage/<username>/<folder>/`
   - User list stored in: `microscopy_storage/users.json`

3. **Key Features**
   - Supports microscopy formats: TIFF, TIF, JPG, JPEG, PNG, ND2, LSM, CZI, DM3, DM4
   - Maximum file size: 200GB per file
   - Concurrent upload limit: 3 simultaneous uploads
   - Upload queue size: 10 pending uploads
   - Minimum free space requirement: 10GB
   - Chunked upload streaming with 64KB chunks
   - Auto-refresh resource monitoring every 30 seconds

### Route Endpoints

- `/` - Main interface with user selection and upload form
- `/api/resources` - JSON API for system resources
- `/set_user/<username>` - Set current user session
- `/set_folder/<username>/<folder>` - Set upload folder for user
- `/switch_user` - Clear session and switch users
- `/upload` - File upload endpoint (POST)

### Configuration Variables

Key settings at the top of `microscopy_upload_server.py`:
- `BASE_UPLOAD_FOLDER` - Base storage directory (default: 'microscopy_storage')
- `ALLOWED_EXTENSIONS` - Supported file extensions
- `MAX_FILE_SIZE` - Maximum file size (200GB)
- `MAX_CONCURRENT_UPLOADS` - Simultaneous upload limit (3)
- `UPLOAD_QUEUE_SIZE` - Queue capacity (10)
- `MIN_FREE_SPACE_GB` - Minimum free disk space (10GB)
- `CHUNK_SIZE` - Streaming chunk size (64KB)
- Server port: 748

### Upload Flow

1. User selects their name from dropdown or creates new user
2. Optionally selects or creates a folder within their directory
3. Uploads files through web interface with progress tracking
4. Server checks disk space and queue availability
5. Files are streamed in chunks to handle large microscopy data
6. Upload status and system resources displayed in real-time