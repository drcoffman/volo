# ZIM File Selector Guide

## Overview
The ZIM File Selector is a web interface that allows you to easily browse and switch between different ZIM files for your Volo knowledge base.

## Features

### 🎨 Modern Web Interface
- Beautiful, responsive design with gradient background
- Real-time file filtering and search
- Visual feedback for selected files
- Statistics dashboard showing total files, size, and selected file

### 📁 Directory Browsing
- Browse ZIM files from any directory
- Recursive search through subdirectories
- Default directory: `/Users/drcoffman/code/zim`
- Easy directory path modification

### 🔄 Dynamic Switching
- Click to select any ZIM file
- One-click switching between ZIM files
- Automatic kiwix-serve restart
- Configuration persistence (saves to `config.ini`)

### 📊 File Information
- File name with emoji indicators
- Relative path display
- Human-readable file sizes
- Total statistics

## How to Use

### 1. Access the Web Interface
Open your browser and navigate to:
```
http://localhost:1255/zim
```

### 2. View Current ZIM File
The page automatically displays the currently loaded ZIM file at the top, including:
- File name
- Full path
- Status (whether the file exists)

### 3. Browse Available Files
The interface will automatically load all ZIM files from the default directory (`/Users/drcoffman/code/zim`).

### 4. Change Directory (Optional)
To browse a different directory:
1. Enter the directory path in the input field
2. Click the "Browse" button or press Enter
3. The page will load all ZIM files from that directory

### 5. Filter Files
Use the search box to filter files by name or path:
- Type any text to filter the list
- Case-insensitive search
- Searches both file names and paths

### 6. Select a ZIM File
1. Click on any ZIM file card to select it
2. The selected card will be highlighted in blue
3. The "Selected File" stat will update

### 7. Switch ZIM File
1. After selecting a file, click the "Select ZIM File" button
2. The system will:
   - Stop the current kiwix-serve process
   - Switch to the new ZIM file
   - Restart kiwix-serve with the new file
   - Update the `config.ini` file
3. You'll see a success message when complete
4. The "Currently Loaded" section will update

## API Endpoints

The ZIM selector also provides REST API endpoints:

### Get Current ZIM File
```bash
GET http://localhost:1255/zim/current
```

**Response:**
```json
{
  "zim_file_path": "/path/to/file.zim",
  "zim_name": "file",
  "exists": true
}
```

### List ZIM Files
```bash
GET http://localhost:1255/zim/list?directory=/path/to/directory
```

**Response:**
```json
{
  "directory": "/path/to/directory",
  "count": 5,
  "zim_files": [
    {
      "path": "/full/path/to/file.zim",
      "name": "file.zim",
      "size": 1234567890,
      "relative_path": "file.zim"
    }
  ]
}
```

### Select ZIM File
```bash
POST http://localhost:1255/zim/select
Content-Type: application/json

{
  "zim_file_path": "/path/to/file.zim"
}
```

**Response:**
```json
{
  "message": "ZIM file switched successfully",
  "zim_file_path": "/path/to/file.zim",
  "zim_name": "file"
}
```

## Technical Details

### File Discovery
- Uses recursive glob pattern matching to find all `.zim` files
- Searches through subdirectories automatically
- Sorts files alphabetically by name

### State Management
- Selected ZIM file is stored in the global `ZIM_FILE_PATH` variable
- Configuration is persisted to `config.ini`
- kiwix-serve automatically restarts with the new file

### Browser Compatibility
- Works in all modern browsers (Chrome, Firefox, Safari, Edge)
- Responsive design works on desktop and tablet
- Uses vanilla JavaScript (no framework dependencies)

## Troubleshooting

### Page Won't Load
- Ensure Flask server is running: `python flaskserver.py`
- Check that you're accessing the correct URL: `http://localhost:1255/zim`
- Verify the `templates` directory exists with `zim_selector.html`

### No Files Showing
- Check that the directory path is correct
- Ensure `.zim` files exist in the specified directory
- Look at the browser console for JavaScript errors

### Can't Switch Files
- Verify the file path is valid and accessible
- Check Flask server logs for error messages
- Ensure you have write permissions for `config.ini`

### kiwix-serve Won't Restart
- Check that kiwix-serve binary is executable
- Look for port conflicts (port 821)
- Review Flask server logs for detailed error messages

## Tips

1. **Large Collections**: Use the filter box to quickly find specific files
2. **Subdirectories**: Files in subdirectories are automatically included
3. **File Sizes**: The total size statistic helps track storage usage
4. **Quick Switching**: The interface remembers your directory selection
5. **Keyboard Navigation**: Press Enter in the directory field to browse

## Support

If you encounter issues:
1. Check the Flask server logs
2. Look at browser console for JavaScript errors
3. Verify file permissions
4. Ensure all dependencies are installed (`flask`, `flask-cors`, etc.)

