# King Lab Data Portal

A multi-user file management system for scientific data uploads, designed specifically for microscopy and large dataset storage.

## Features

- **Multi-user Support**: Individual user accounts with separate storage spaces
- **Large File Handling**: Supports files up to 200GB
- **File Organization**: Create and manage folders for better organization
- **File Browser**: Browse, preview, and download uploaded files
- **Real-time Monitoring**: Live system resource monitoring (CPU, memory, disk usage)
- **Drag & Drop**: Intuitive drag-and-drop file upload interface
- **Auto-upload**: Files automatically upload upon selection
- **Format Support**: TIFF, ND2, LSM, CZI, DM3, DM4, JPEG, PNG, FCS formats

## Prerequisites

- Python 3.7+
- Flask web framework
- Modern web browser (Chrome, Firefox, Safari, Edge)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd MICROSCOPY_SERVER
```

2. Install required Python packages:
```bash
pip install flask werkzeug psutil
```

3. Ensure the storage directory exists:
```bash
mkdir -p storage
```

## Configuration

### User Management

Users are defined in `storage/users.json`:
```json
[
  "Nicole",
  "Alain",
  "Michael",
  "Stefany",
  "Chrisa",
  "Jacob"
]
```

To add new users, simply edit this file and add names to the list.

### Server Settings

Key settings in `upload_server.py`:
- `BASE_UPLOAD_FOLDER`: Storage directory (default: 'storage')
- `MAX_FILE_SIZE`: Maximum file size (default: 200GB)
- `MAX_CONCURRENT_UPLOADS`: Simultaneous upload limit (default: 3)
- `MIN_FREE_SPACE_GB`: Minimum required disk space (default: 10GB)

## Usage

### Starting the Server

```bash
python upload_server.py
```

The server will start on port 748 by default. Access it at:
```
http://localhost:748
```

### Uploading Files

1. Select your username from the dropdown
2. Choose or create a folder for organization (optional)
3. Drag and drop files or click "Choose Files"
4. Files will automatically begin uploading

### File Management

- **Browse Files**: View your uploaded files in a tree structure
- **Preview**: Click "Preview" to view compatible files
- **Download**: Click "Download" to retrieve files
- **Folders**: Organize files into folders for better management

## System Architecture

```
MICROSCOPY_SERVER/
├── upload_server.py      # Main Flask application
├── storage/              # Data storage directory
│   ├── users.json       # User configuration
│   └── [user_folders]/  # Individual user directories
├── choanoflagellate.png # Logo/favicon
├── test_image.py        # Testing script
├── CLAUDE.md           # Development documentation
└── README.md           # This file
```

## API Endpoints

- `/` - Main interface
- `/set_user/<username>` - Set active user
- `/upload` - File upload endpoint
- `/api/user-files/<username>` - Get user's file tree (JSON)
- `/preview/<username>/<path>` - Preview files
- `/download/<username>/<path>` - Download files
- `/static/<filename>` - Serve static assets

## Security Notes

- Files are stored in user-specific directories
- Filenames are sanitized to prevent directory traversal
- Session management for user persistence
- File type restrictions for safety

## Troubleshooting

### Users Not Appearing
- Check that `storage/users.json` has valid JSON syntax (no trailing commas)
- Ensure the storage directory exists and is readable

### Upload Issues
- Verify sufficient disk space (minimum 10GB required)
- Check that file format is supported
- Ensure file size is under 200GB limit

### Server Won't Start
- Confirm port 748 is not in use
- Check Python dependencies are installed
- Verify write permissions for storage directory

## Development

For development and debugging:
```bash
# Run with debug mode
python upload_server.py
# Server includes debug output by default
```

## Testing

Test the image endpoint:
```bash
python test_image.py
```

## Performance Considerations

- The server uses streaming for large file uploads
- Concurrent upload limits prevent system overload
- Real-time resource monitoring helps track system health
- Files are chunked at 64KB for efficient transfer

## Browser Compatibility

Tested and supported on:
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## License

Internal use only - King Lab, UC Berkeley

## Support

For issues or questions, contact the King Lab IT administrator.