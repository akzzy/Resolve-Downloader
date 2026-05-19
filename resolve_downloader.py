import os
import sys
import json
import urllib.parse
import urllib.request
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import yt_dlp

# Programmatically configure DaVinci Resolve scripting environment variables for Windows
def setup_resolve_env():
    if sys.platform == "win32":
        # Resolve Scripting API path
        program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        api_path = os.path.join(program_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "API")
        if not os.environ.get("RESOLVE_SCRIPT_API"):
            os.environ["RESOLVE_SCRIPT_API"] = api_path
            
        # Resolve Scripting Library path
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        lib_path = os.path.join(program_files, "Blackmagic Design", "DaVinci Resolve", "fusionscript.dll")
        if not os.environ.get("RESOLVE_SCRIPT_LIB"):
            os.environ["RESOLVE_SCRIPT_LIB"] = lib_path
            
        # Append Modules folder to path
        modules_path = os.path.join(program_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules")
        if os.path.isdir(modules_path) and modules_path not in sys.path:
            sys.path.append(modules_path)

# Initialize paths at import time
setup_resolve_env()

# Global configuration and state
DEFAULT_PORT = 8554
PROGRESS_STATE = {
    "status": "idle",       # "idle", "fetching", "downloading", "merging", "importing", "success", "warning", "error"
    "percent": 0.0,
    "speed": "0 KB/s",
    "eta": "Unknown",
    "message": "",
    "error": None
}
LAST_IMPORTED_PATH = None

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

def load_settings():
    default_path = os.path.join(os.path.expanduser('~'), 'Downloads')
    default_settings = {"download_dir": default_path}
    if not os.path.exists(SETTINGS_FILE):
        return default_settings
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            path = data.get("download_dir", default_path)
            return {"download_dir": path}
    except:
        return default_settings

def save_settings(download_dir):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"download_dir": download_dir}, f, indent=4)
        return True
    except:
        return False

# ==============================================================================
# RESOLVE INTEGRATION
# ==============================================================================
def import_to_resolve(file_path):
    """Imports the downloaded file into DaVinci Resolve Media Pool and current timeline."""
    try:
        setup_resolve_env()
        import DaVinciResolveScript as dvr
    except Exception as e:
        error_msg = str(e)
        if "fusionscript" in error_msg.lower() or "initialization" in error_msg.lower():
            return False, "Resolve API initialization failed. Ensure Python is 64-bit and DaVinci Resolve preferences -> System -> General -> External Scripting is set to 'Local' or 'Network'."
        return False, f"Could not load Resolve Scripting module: {error_msg}. Ensure Python scripting is enabled."

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        return False, "Could not connect to DaVinci Resolve. Please ensure Resolve is running."
        
    pm = resolve.GetProjectManager()
    if not pm:
        return False, "Failed to retrieve Project Manager."
        
    proj = pm.GetCurrentProject()
    if not proj:
        return False, "No active project found. Please open a project in DaVinci Resolve."
        
    mp = proj.GetMediaPool()
    if not mp:
        return False, "Failed to retrieve Media Pool."
        
    abs_path = os.path.abspath(file_path)
    if not os.path.exists(abs_path):
        return False, f"File does not exist: {abs_path}"
        
    # Add to Media Pool
    ms = resolve.GetMediaStorage()
    if not ms:
        return False, "Failed to retrieve Media Storage object."
    clips = ms.AddItemListToMediaPool([abs_path])
    if not clips or len(clips) == 0:
        return False, "Failed to import file into Media Pool. Codec may not be supported."
        
    return True, "Imported into Media Pool successfully!"

def append_to_active_timeline(file_path):
    """Appends the previously imported Media Pool item to the active timeline in Resolve."""
    try:
        setup_resolve_env()
        import DaVinciResolveScript as dvr
    except Exception as e:
        return False, f"Could not load Resolve Scripting module: {str(e)}"

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        return False, "Could not connect to DaVinci Resolve. Please ensure Resolve is running."
        
    pm = resolve.GetProjectManager()
    if not pm:
        return False, "Failed to retrieve Project Manager."
        
    proj = pm.GetCurrentProject()
    if not proj:
        return False, "No active project found. Please open a project in DaVinci Resolve."
        
    mp = proj.GetMediaPool()
    if not mp:
        return False, "Failed to retrieve Media Pool."
        
    # Get current folder and search for the clip by file path
    folder = mp.GetCurrentFolder()
    if not folder:
        return False, "Failed to retrieve current Media Pool folder."
        
    clips = folder.GetClipList()
    target_clip = None
    abs_path = os.path.abspath(file_path).lower()
    
    if clips:
        for clip in clips:
            clip_path = clip.GetClipProperty("File Path")
            if clip_path and os.path.abspath(clip_path).lower() == abs_path:
                target_clip = clip
                break
                
    if not target_clip:
        # Fallback: import the item using MediaStorage to get the clip object reference
        ms = resolve.GetMediaStorage()
        if ms:
            added = ms.AddItemListToMediaPool([file_path])
            if added and len(added) > 0:
                target_clip = added[0]
                
    if not target_clip:
        return False, "Could not locate the imported file in your Media Pool."
        
    # Add to active timeline
    timeline = proj.GetCurrentTimeline()
    if not timeline:
        # Create a new timeline if none exists
        timeline = mp.CreateTimelineFromClips("Downloaded Clips", [target_clip])
        if not timeline:
            return False, "Imported into Media Pool, but could not create a new timeline."
    else:
        mp.AppendToTimeline([target_clip])
        
    return True, "Successfully appended clip to the active timeline!"

# ==============================================================================
# YT-DLP CORE FUNCTIONS
# ==============================================================================
def fetch_video_info(url):
    """Fetches video information and available resolutions using yt-dlp."""
    ydl_opts = {
        'skip_download': True,
        'quiet': True,
        'no_warnings': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        
        # Identify platform
        url_lower = url.lower()
        if "youtube.com" in url_lower or "youtu.be" in url_lower:
            platform = "youtube"
        elif "reddit.com" in url_lower or "r/" in url_lower:
            platform = "reddit"
        elif "instagram.com" in url_lower or "instagr.am" in url_lower:
            platform = "instagram"
        elif "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.com" in url_lower:
            platform = "facebook"
        elif "twitter.com" in url_lower or "x.com" in url_lower:
            platform = "twitter"
        else:
            platform = "video"
            
        formats = info.get('formats', [])
        
        # Deduplicate and sort resolutions based on their standard tier (shorter dimension)
        resolutions = {}
        for f in formats:
            w = f.get('width')
            h = f.get('height')
            if f.get('vcodec') != 'none' and h:
                # If width is present, the standard tier is min(width, height)
                # If width is missing, default to height
                tier = min(w, h) if w else h
                
                # Keep the format height as value (which we pass to yt-dlp to download)
                # but associate it with the standard tier
                if tier not in resolutions or h > resolutions[tier]:
                    resolutions[tier] = h
                    
        sorted_tiers = sorted(list(resolutions.keys()), reverse=True)
        res_list = []
        for tier in sorted_tiers:
            h = resolutions[tier]
            if tier >= 2160:
                name = f"{tier}p (4K)"
            else:
                name = f"{tier}p"
            res_list.append({"height": h, "name": name})
            
        # Add audio only option
        res_list.append({"height": "audio", "name": "Audio Only (MP3)"})
            
        return {
            "title": info.get('title', 'Unknown Title'),
            "thumbnail": info.get('thumbnail', ''),
            "duration": info.get('duration', 0),
            "uploader": info.get('uploader', 'Unknown Creator'),
            "resolutions": res_list,
            "platform": platform,
            "url": url
        }

def download_task_thread(url, height):
    """Worker thread that downloads the video and triggers Resolve import."""
    global PROGRESS_STATE
    
    PROGRESS_STATE = {
        "status": "fetching",
        "percent": 0.0,
        "speed": "0 KB/s",
        "eta": "Unknown",
        "message": "Initializing download streams...",
        "error": None
    }
    
    # Configure formatting for best Resolve compatibility (H.264 MP4)
    if height == 'audio':
        format_selector = 'bestaudio/best'
    else:
        format_selector = f'bestvideo[height<={height}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[height<={height}][ext=mp4]/best'
        
    settings = load_settings()
    downloads_dir = settings.get("download_dir")
    try:
        if not os.path.exists(downloads_dir):
            os.makedirs(downloads_dir)
    except Exception:
        downloads_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        if not os.path.exists(downloads_dir):
            os.makedirs(downloads_dir)
        
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    def clean_ansi(text):
        return ansi_escape.sub('', text) if text else text

    # Fetch info first dynamically with clean fallback
    fetch_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False
    }
    try:
        with yt_dlp.YoutubeDL(fetch_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        PROGRESS_STATE['status'] = 'error'
        PROGRESS_STATE['error'] = str(e)
        PROGRESS_STATE['message'] = f"Failed to retrieve video metadata: {str(e)}"
        return

    # Sanitize video title for Windows & DaVinci ASCII safety (strips emojis & unicode symbols)
    raw_title = info.get('title', 'video')
    # Remove any non-ASCII characters (including emojis)
    clean_title = re.sub(r'[^\x00-\x7F]+', '', raw_title)
    # Keep only safe alphanumeric characters, spaces, hyphens, and underscores
    clean_title = re.sub(r'[^a-zA-Z0-9_\-\s]', '', clean_title)
    # squash duplicate spaces
    clean_title = " ".join(clean_title.split()).strip()
    if not clean_title:
        clean_title = "video"
        
    safe_base = f"{clean_title}_{info.get('id', 'clip')}"
    if len(safe_base) > 120:
        safe_base = safe_base[:120]
        
    outtmpl = os.path.join(downloads_dir, f"{safe_base}.%(ext)s")

    def ytdlp_hook(d):
        global PROGRESS_STATE
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            percent = round((downloaded / total) * 100.0, 1) if total > 0 else 0.0
            
            PROGRESS_STATE['status'] = 'downloading'
            PROGRESS_STATE['percent'] = percent
            PROGRESS_STATE['speed'] = clean_ansi(d.get('_speed_str', '0 KB/s'))
            PROGRESS_STATE['eta'] = clean_ansi(d.get('_eta_str', 'Unknown'))
            PROGRESS_STATE['message'] = f"Downloading stream: {percent}%"
        elif d['status'] == 'finished':
            PROGRESS_STATE['status'] = 'merging'
            PROGRESS_STATE['percent'] = 90.0
            PROGRESS_STATE['message'] = "Merging audio & video streams..."
            
    ydl_opts = {
        'format': format_selector,
        'outtmpl': outtmpl,
        'progress_hooks': [ytdlp_hook],
        'merge_output_format': 'mp4' if height != 'audio' else None,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }] if height == 'audio' else [],
        'quiet': True,
        'no_warnings': True,
        'nocolor': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            filename = ydl.prepare_filename(info)
            
            # Predict actual final filename post-processor swaps
            base, _ = os.path.splitext(filename)
            final_path = base + ".mp3" if height == 'audio' else base + ".mp4"
            
            PROGRESS_STATE['message'] = "Connecting to content server..."
            ydl.download([url])
            
            # Resolve file target verification
            if not os.path.exists(final_path):
                if os.path.exists(filename):
                    final_path = filename
                else:
                    matching = [f for f in os.listdir(downloads_dir) if f.startswith(os.path.basename(base))]
                    if matching:
                        final_path = os.path.join(downloads_dir, matching[0])
                    else:
                        raise FileNotFoundError("Downloaded file was not found on disk.")
                        
            PROGRESS_STATE['status'] = 'importing'
            PROGRESS_STATE['percent'] = 95.0
            PROGRESS_STATE['message'] = "Natively importing file to DaVinci Resolve..."
            
            success, msg = import_to_resolve(final_path)
            
            if success:
                global LAST_IMPORTED_PATH
                LAST_IMPORTED_PATH = final_path
                PROGRESS_STATE['status'] = 'success'
                PROGRESS_STATE['percent'] = 100.0
                PROGRESS_STATE['message'] = msg
            else:
                PROGRESS_STATE['status'] = 'warning'
                PROGRESS_STATE['percent'] = 100.0
                PROGRESS_STATE['message'] = f"Downloaded successfully! Resolve Import Warning: {msg}"
                
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        try:
            with open(r"j:\Dev\Davinci down\downloader_error.log", "w", encoding="utf-8") as f_err:
                f_err.write(tb_str)
        except Exception:
            pass
        PROGRESS_STATE['status'] = 'error'
        PROGRESS_STATE['error'] = str(e)
        PROGRESS_STATE['message'] = f"Download Failed: {str(e)}"

# ==============================================================================
# WEB SERVER ROUTING
# ==============================================================================
class DownloaderHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Mute logging to stdout to keep Electron logs perfectly clean
        pass

    def do_GET(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        query = urllib.parse.parse_qs(url_parts.query)
        
        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
            
        elif path == '/api/status':
            # Check if Resolve API is accessible
            resolve_status = False
            try:
                import DaVinciResolveScript as dvr
                resolve = dvr.scriptapp("Resolve")
                if resolve:
                    resolve_status = True
            except:
                pass
            self.send_json({"status": "ready", "resolve_connected": resolve_status})
            
        elif path == '/api/progress':
            global PROGRESS_STATE
            self.send_json(PROGRESS_STATE)
            
        elif path == '/api/fetch':
            url = query.get('url', [''])[0]
            if not url:
                self.send_error_json("Please provide a valid URL.")
                return
            try:
                info = fetch_video_info(url)
                self.send_json({"success": True, "data": info})
            except Exception as e:
                self.send_error_json(str(e))
        elif path == '/api/settings':
            settings = load_settings()
            self.send_json(settings)
        elif path == '/api/proxy-image':
            img_url = query.get('url', [''])[0]
            if not img_url:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"No URL provided")
                return
            try:
                req = urllib.request.Request(
                    img_url,
                    headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    img_data = response.read()
                    content_type = response.headers.get('Content-Type', 'image/jpeg')
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Cache-Control', 'max-age=86400')
                self.end_headers()
                self.wfile.write(img_data)
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            
    def do_POST(self):
        url_parts = urllib.parse.urlparse(self.path)
        path = url_parts.path
        
        if path == '/api/download':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
            except:
                self.send_error_json("Invalid payload.")
                return
                
            url = data.get('url')
            height = data.get('height')
            
            if not url or not height:
                self.send_error_json("URL and selection height are required.")
                return
                
            # Spawn the thread
            threading.Thread(target=download_task_thread, args=(url, height), daemon=True).start()
            self.send_json({"success": True, "message": "Downloader initialized."})
            
        elif path == '/api/add-to-timeline':
            global LAST_IMPORTED_PATH
            if not LAST_IMPORTED_PATH:
                self.send_error_json("No recently downloaded file found to add to the timeline.")
                return
                
            success, msg = append_to_active_timeline(LAST_IMPORTED_PATH)
            if success:
                self.send_json({"success": True, "message": msg})
            else:
                self.send_error_json(msg)
                
        elif path == '/api/settings':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            try:
                data = json.loads(post_data)
            except:
                self.send_error_json("Invalid payload.")
                return
                
            download_dir = data.get('download_dir')
            if not download_dir:
                self.send_error_json("Download directory is required.")
                return
                
            success = save_settings(download_dir)
            if success:
                self.send_json({"success": True, "message": "Settings updated successfully."})
            else:
                self.send_error_json("Failed to save settings.")
                
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            
    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
        
    def send_error_json(self, msg):
        self.send_response(400)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"success": False, "error": msg}).encode('utf-8'))

# ==============================================================================
# INSTALLATION COMMAND HANDLER
# ==============================================================================
def install_plugin():
    print("=======================================================")
    print(" INSTALLING NATIVE RESOLVE WORKFLOW INTEGRATION...")
    print("=======================================================")
    
    program_data = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    plugins_dir = os.path.join(
        program_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Workflow Integration Plugins"
    )
    
    try:
        os.makedirs(plugins_dir, exist_ok=True)
    except Exception as e:
        print(f"Error: Could not access program directory structure: {e}")
        sys.exit(1)
        
    # Delete old folder if exists
    shutil.rmtree(os.path.join(plugins_dir, "ResolveDownloader"), ignore_errors=True)
    
    target_plugin_dir = os.path.join(plugins_dir, "com.antigravity.resolve.downloader")
    os.makedirs(target_plugin_dir, exist_ok=True)
    
    # 1. Copy script self-copy
    current_script = os.path.abspath(__file__)
    target_script = os.path.join(target_plugin_dir, "resolve_downloader.py")
    try:
        shutil.copy2(current_script, target_script)
    except Exception as e:
        print(f"Error copying script package: {e}")
        sys.exit(1)
        
    # Copy WorkflowIntegration.node from Examples to ensure 100% registration validation
    examples_node = os.path.join(
        program_data, "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Workflow Integrations", "Examples", "SamplePlugin", "WorkflowIntegration.node"
    )
    if os.path.exists(examples_node):
        try:
            shutil.copy2(examples_node, os.path.join(target_plugin_dir, "WorkflowIntegration.node"))
        except Exception as e:
            print(f"Notice: Could not copy WorkflowIntegration.node: {e}")
        
    # 2. Write manifest.xml
    manifest_xml = """<?xml version="1.0" encoding="UTF-8"?>
<BlackmagicDesign>
    <Plugin>
        <Id>com.antigravity.resolve.downloader</Id>
        <Name>Resolve Video Downloader</Name>
        <Version>1.0</Version>
        <Description>YouTube and Reddit Video Downloader with auto timeline importing.</Description>
        <FilePath>main.js</FilePath>
    </Plugin>
</BlackmagicDesign>
"""
    with open(os.path.join(target_plugin_dir, "manifest.xml"), "w", encoding="utf-8") as f:
        f.write(manifest_xml)
        
    # 3. Write package.json
    package_json = """{
  "name": "resolve-video-downloader",
  "version": "1.0.0",
  "main": "main.js"
}
"""
    with open(os.path.join(target_plugin_dir, "package.json"), "w", encoding="utf-8") as f:
        f.write(package_json)
        
    # 4. Write main.js (Electron launchpad)
    main_js = """const { app, BrowserWindow } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');

let mainWindow = null;
let pythonProcess = null;
const PORT = 8554;

function startPythonServer() {
    const pythonScript = path.join(__dirname, 'resolve_downloader.py');
    
    pythonProcess = spawn('python', [pythonScript, '--server', '--port', PORT], {
        cwd: __dirname,
        stdio: 'ignore',
        windowsHide: true
    });

    pythonProcess.on('error', (err) => {
        console.error('Failed to spawn background python server:', err);
    });
}

function checkServerReady(callback, retries = 30) {
    if (retries <= 0) {
        callback(false);
        return;
    }
    http.get(`http://localhost:${PORT}/api/status`, (res) => {
        if (res.statusCode === 200) {
            callback(true);
        } else {
            setTimeout(() => checkServerReady(callback, retries - 1), 250);
        }
    }).on('error', () => {
        setTimeout(() => checkServerReady(callback, retries - 1), 250);
    });
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 800,
        height: 700,
        title: "Resolve Video Downloader",
        autoHideMenuBar: true,
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true
        }
    });

    mainWindow.loadURL(`http://localhost:${PORT}`);

    mainWindow.on('closed', () => {
        mainWindow = null;
    });
}

app.whenReady().then(() => {
    startPythonServer();
    checkServerReady((success) => {
        if (success) {
            createWindow();
        } else {
            console.error("Python server failed to report ready.");
            createWindow();
        }
    });
});

app.on('window-all-closed', () => {
    if (pythonProcess) {
        pythonProcess.kill();
    }
    app.quit();
});
"""
    with open(os.path.join(target_plugin_dir, "main.js"), "w", encoding="utf-8") as f:
        f.write(main_js)
        
    print("\n=======================================================")
    print(" NATIVE INSTALLATION COMPLETED SUCCESSFULLY!")
    print("=======================================================")
    print(f"Plugin registered at: {target_plugin_dir}")
    print("\nNext Steps:")
    print("1. Restart DaVinci Resolve Studio.")
    print("2. Open the panel by navigating to:")
    print("   Workspace -> Workflow Integrations -> Resolve Video Downloader")
    print("=======================================================\n")

# ==============================================================================
# EMBEDDED HIGH-END GLASSMORPHISM FRONTEND TEMPLATE
# ==============================================================================
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resolve Video Downloader</title>
    <!-- Google Fonts Outfit & Inter -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0c10;
            --card-bg: rgba(20, 22, 33, 0.45);
            --border-color: rgba(255, 255, 255, 0.08);
            --accent-primary: #7c3aed;
            --accent-secondary: #2563eb;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --success-color: #10b981;
            --warning-color: #f59e0b;
            --danger-color: #ef4444;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Inter', sans-serif;
            -webkit-font-smoothing: antialiased;
        }

        body {
            background-color: var(--bg-color);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow-x: hidden;
            background-image: 
                radial-gradient(circle at 10% 20%, rgba(124, 58, 237, 0.15) 0%, transparent 40%),
                radial-gradient(circle at 90% 80%, rgba(37, 99, 235, 0.15) 0%, transparent 40%);
            padding: 20px;
        }

        .container {
            width: 100%;
            max-width: 650px;
            perspective: 1000px;
        }

        /* Glassmorphism Panel card styling */
        .glass-card {
            background: var(--card-bg);
            backdrop-filter: blur(16px) saturate(180%);
            -webkit-backdrop-filter: blur(16px) saturate(180%);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
            animation: slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1);
            position: relative;
            overflow: hidden;
        }

        /* Glowing light accent elements */
        .glass-card::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            height: 150px;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.05), transparent);
            transform: translateX(-100%);
            transition: 0.6s;
            pointer-events: none;
        }

        .glass-card:hover::before {
            transform: translateX(100%);
        }

        header {
            text-align: center;
            margin-bottom: 25px;
        }

        h1 {
            font-family: 'Outfit', sans-serif;
            font-size: 2.2rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a78bfa 0%, #60a5fa 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
            letter-spacing: -0.5px;
            display: inline-flex;
            align-items: center;
            gap: 10px;
        }

        .subtitle {
            color: var(--text-muted);
            font-size: 0.95rem;
            font-weight: 300;
        }

        /* Form elements and inputs */
        .input-group {
            display: flex;
            position: relative;
            margin-bottom: 20px;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 4px;
            transition: all 0.3s ease;
        }

        .input-group:focus-within {
            border-color: rgba(167, 139, 250, 0.6);
            box-shadow: 0 0 15px rgba(124, 58, 237, 0.25);
        }

        input[type="text"] {
            flex-grow: 1;
            background: transparent;
            border: none;
            outline: none;
            color: var(--text-main);
            padding: 12px 16px;
            font-size: 1rem;
        }

        input[type="text"]::placeholder {
            color: rgba(255, 255, 255, 0.25);
        }

        .btn-analyze {
            background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
            border: none;
            border-radius: 10px;
            color: white;
            padding: 0 24px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            box-shadow: 0 4px 15px rgba(124, 58, 237, 0.3);
        }

        .btn-analyze:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 20px rgba(124, 58, 237, 0.5);
            filter: brightness(1.1);
        }

        .btn-analyze:active {
            transform: translateY(1px);
        }

        .btn-paste {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 10px;
            color: var(--text-muted);
            width: 44px;
            height: 44px;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 4px;
            flex-shrink: 0;
        }

        .btn-paste:hover {
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-main);
            border-color: rgba(255, 255, 255, 0.2);
            box-shadow: 0 4px 12px rgba(255, 255, 255, 0.05);
        }

        .btn-paste:active {
            transform: scale(0.96);
        }

        /* Video Card metadata styles */
        .video-card {
            display: none;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 20px;
            animation: fadeInDown 0.5s cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }

        .video-meta-wrapper {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }

        .thumbnail-container {
            width: 160px;
            height: 90px;
            border-radius: 10px;
            overflow: hidden;
            position: relative;
            background: rgba(0,0,0,0.4);
            border: 1px solid rgba(255, 255, 255, 0.05);
            flex-shrink: 0;
        }

        .thumbnail-container img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }

        .duration-badge {
            position: absolute;
            bottom: 6px;
            right: 6px;
            background: rgba(0, 0, 0, 0.85);
            color: white;
            font-size: 0.75rem;
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
        }

        .video-details {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }

        .video-title {
            font-family: 'Outfit', sans-serif;
            font-size: 1.15rem;
            font-weight: 600;
            line-height: 1.4;
            margin-bottom: 8px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .video-author {
            color: var(--text-muted);
            font-size: 0.85rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .platform-badge {
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: inline-flex;
            align-items: center;
            margin-bottom: 6px;
        }

        .badge-youtube {
            color: #f87171;
        }

        .badge-reddit {
            color: #fb923c;
        }

        .badge-instagram {
            color: #f472b6;
        }

        .badge-facebook {
            color: #60a5fa;
        }

        .badge-twitter {
            color: #e2e8f0;
        }

        .badge-video {
            color: #a78bfa;
        }

        /* Quality selection interactive selector */
        .option-group {
            margin-bottom: 20px;
        }

        .option-label {
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: 500;
            margin-bottom: 8px;
            display: block;
        }

        .select-wrapper {
            position: relative;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            overflow: hidden;
            transition: all 0.3s ease;
        }

        .select-wrapper:hover {
            border-color: rgba(255, 255, 255, 0.15);
        }

        select {
            width: 100%;
            background: transparent;
            border: none;
            outline: none;
            color: var(--text-main);
            padding: 12px 16px;
            font-size: 0.95rem;
            cursor: pointer;
            -webkit-appearance: none;
            -moz-appearance: none;
            appearance: none;
        }

        .select-wrapper::after {
            content: '▼';
            position: absolute;
            right: 16px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 0.7rem;
            color: var(--text-muted);
            pointer-events: none;
        }

        .btn-download {
            width: 100%;
            background: linear-gradient(135deg, var(--accent-secondary) 0%, var(--accent-primary) 100%);
            border: none;
            border-radius: 12px;
            color: white;
            padding: 14px;
            font-size: 1.05rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            box-shadow: 0 4px 20px rgba(37, 99, 235, 0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }

        .btn-download:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(37, 99, 235, 0.5);
            filter: brightness(1.1);
        }

        .btn-download:active {
            transform: translateY(0);
        }

        /* Progress Card & Bars Styles */
        .progress-card {
            display: none;
            background: rgba(255, 255, 255, 0.015);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            margin-top: 10px;
            animation: fadeIn 0.4s ease forwards;
        }

        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .status-msg {
            font-size: 0.95rem;
            font-weight: 500;
            color: var(--text-main);
        }

        .percent-text {
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--accent-primary);
            font-family: 'Outfit', sans-serif;
        }

        .progress-bar-container {
            width: 100%;
            height: 8px;
            background: rgba(255, 255, 255, 0.05);
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 16px;
            position: relative;
        }

        .progress-bar-fill {
            width: 0%;
            height: 100%;
            background: linear-gradient(90deg, var(--accent-secondary), var(--accent-primary));
            border-radius: 10px;
            transition: width 0.3s cubic-bezier(0.1, 0.8, 0.1, 1);
            box-shadow: 0 0 10px rgba(124, 58, 237, 0.5);
        }

        .metrics-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }

        .metric-item {
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid rgba(255, 255, 255, 0.03);
            border-radius: 10px;
            padding: 10px 14px;
        }

        .metric-title {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
        }

        .metric-value {
            font-size: 0.95rem;
            font-weight: 600;
        }

        .btn-timeline {
            background: rgba(16, 185, 129, 0.08);
            border: 1px solid rgba(16, 185, 129, 0.25);
            border-radius: 12px;
            color: #34d399;
            padding: 12px 20px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 100%;
            margin-top: 15px;
            box-shadow: 0 4px 15px rgba(16, 185, 129, 0.05);
        }

        .btn-timeline:hover {
            background: rgba(16, 185, 129, 0.18);
            border-color: rgba(16, 185, 129, 0.5);
            box-shadow: 0 6px 20px rgba(16, 185, 129, 0.2);
            transform: translateY(-1px);
        }

        .btn-timeline:active {
            transform: translateY(1px);
        }

        .btn-timeline:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            pointer-events: none;
        }

        .btn-settings {
            position: absolute;
            top: 20px;
            right: 20px;
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 8px;
            border-radius: 50%;
        }

        .btn-settings:hover {
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.05);
            transform: rotate(45deg);
        }

        /* Settings Modal Overlay */
        .modal-overlay {
            display: none;
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(11, 12, 16, 0.85);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            z-index: 100;
            animation: fadeIn 0.3s ease forwards;
            justify-content: center;
            align-items: center;
            padding: 20px;
            border-radius: 24px;
        }

        .modal-content {
            background: rgba(20, 22, 33, 0.95);
            border: 1px solid var(--border-color);
            border-radius: 18px;
            width: 100%;
            max-width: 440px;
            padding: 24px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.6);
            animation: slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards;
            position: relative;
        }

        .modal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .modal-title {
            font-family: 'Outfit', sans-serif;
            font-size: 1.3rem;
            font-weight: 600;
            color: var(--text-main);
        }

        .btn-close-modal {
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 1.2rem;
            cursor: pointer;
            transition: color 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 4px;
        }

        .btn-close-modal:hover {
            color: var(--text-main);
        }

        .settings-input-group {
            margin-bottom: 20px;
            text-align: left;
        }

        .settings-label {
            display: block;
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: 500;
            margin-bottom: 8px;
        }

        .settings-input {
            width: 100%;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: var(--text-main);
            padding: 12px 16px;
            font-size: 0.95rem;
            outline: none;
            transition: border-color 0.3s;
            box-sizing: border-box;
        }

        .settings-input:focus {
            border-color: rgba(124, 58, 237, 0.5);
        }

        .btn-save-settings {
            background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
            border: none;
            border-radius: 10px;
            color: white;
            padding: 12px 20px;
            font-weight: 600;
            font-size: 0.95rem;
            cursor: pointer;
            transition: all 0.3s ease;
            width: 100%;
            text-align: center;
        }

        .btn-save-settings:hover {
            filter: brightness(1.1);
            box-shadow: 0 4px 15px rgba(124, 58, 237, 0.4);
        }

        /* Footer alerts & Status lights */
        .footer-status {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 20px;
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .status-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: var(--danger-color);
            transition: all 0.3s ease;
        }

        .status-dot.active {
            background-color: var(--success-color);
            box-shadow: 0 0 8px var(--success-color);
        }

        /* Animation keyframes */
        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeInDown {
            from {
                opacity: 0;
                transform: translateY(-15px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }

        /* Custom scrollbar for glassmorphic select list */
        select option {
            background-color: #12131a;
            color: var(--text-main);
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="glass-card">
            <header style="position: relative;">
                <button id="btnSettings" class="btn-settings" title="Settings">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-settings"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                </button>
                <h1>
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-download-cloud"><polyline points="8 17 12 21 16 17"></polyline><line x1="12" y1="12" x2="12" y2="21"></line><path d="M20.88 18.09A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.29"></path></svg>
                    Resolve Downloader
                </h1>
                <p class="subtitle">Universal media downloader & native importer</p>
            </header>

            <!-- URL Input Form Section -->
            <div class="input-group">
                <input type="text" id="urlInput" placeholder="Paste link here (YouTube, Reddit, Instagram, FB, X)..." autocomplete="off">
                <button class="btn-paste" id="btnPaste" title="Paste Link from Clipboard">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-clipboard"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect></svg>
                </button>
                <button class="btn-analyze" id="btnAnalyze">
                    <span>Fetch</span>
                </button>
            </div>

            <!-- Video details display panel -->
            <div class="video-card" id="videoCard">
                <div class="video-meta-wrapper">
                    <div class="thumbnail-container">
                        <img id="vidThumb" src="" alt="Thumbnail">
                        <span class="duration-badge" id="vidDuration">0:00</span>
                    </div>
                    <div class="video-details">
                        <div class="platform-badge" id="vidPlatform">YouTube</div>
                        <h2 class="video-title" id="vidTitle">Video Title</h2>
                        <div class="video-author" id="vidAuthor">Channel Name</div>
                    </div>
                </div>

                <div class="option-group">
                    <label class="option-label">Select Resolution / Format</label>
                    <div class="select-wrapper">
                        <select id="resSelect">
                            <!-- Resolutions injected dynamically -->
                        </select>
                    </div>
                </div>

                <button class="btn-download" id="btnDownload">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-zap"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
                    Download & Import to Resolve
                </button>
            </div>

            <!-- Download active progress panel -->
            <div class="progress-card" id="progressCard">
                <div class="progress-header">
                    <span class="status-msg" id="progressMsg">Downloading video...</span>
                    <span class="percent-text" id="progressPercent">0%</span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar-fill" id="progressBarFill"></div>
                </div>
                <div class="metrics-grid">
                    <div class="metric-item">
                        <div class="metric-title">Speed</div>
                        <div class="metric-value" id="progressSpeed">0 KB/s</div>
                    </div>
                    <div class="metric-item">
                        <div class="metric-title">Remaining</div>
                        <div class="metric-value" id="progressEta">Unknown</div>
                    </div>
                </div>
                <div id="timelineActionContainer" style="display: none; text-align: center;">
                    <button class="btn-timeline" id="btnAddToTimeline">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-plus-circle"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="16"></line><line x1="8" y1="12" x2="16" y2="12"></line></svg>
                        Add to Active Timeline
                    </button>
                </div>
            </div>

            <!-- Resolve native connector status indicator -->
            <div class="footer-status">
                <span class="status-dot" id="statusDot"></span>
                <span id="statusText">Connecting to DaVinci Resolve API...</span>
            </div>

            <!-- Settings Modal -->
            <div class="modal-overlay" id="settingsModal">
                <div class="modal-content">
                    <div class="modal-header">
                        <span class="modal-title">Plugin Settings</span>
                        <button class="btn-close-modal" id="btnCloseSettings">✕</button>
                    </div>
                    <div class="settings-input-group">
                        <label class="settings-label">Target Download Directory</label>
                        <input type="text" class="settings-input" id="settingDownloadDir" placeholder="e.g. C:\\Downloads">
                    </div>
                    <button class="btn-save-settings" id="btnSaveSettings">Save Configuration</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        // DOM Bindings
        const urlInput = document.getElementById('urlInput');
        const btnAnalyze = document.getElementById('btnAnalyze');
        const videoCard = document.getElementById('videoCard');
        const progressCard = document.getElementById('progressCard');
        
        const vidThumb = document.getElementById('vidThumb');
        const vidDuration = document.getElementById('vidDuration');
        const vidTitle = document.getElementById('vidTitle');
        const vidAuthor = document.getElementById('vidAuthor');
        const vidPlatform = document.getElementById('vidPlatform');
        const resSelect = document.getElementById('resSelect');
        const btnDownload = document.getElementById('btnDownload');
        
        const progressMsg = document.getElementById('progressMsg');
        const progressPercent = document.getElementById('progressPercent');
        const progressBarFill = document.getElementById('progressBarFill');
        const progressSpeed = document.getElementById('progressSpeed');
        const progressEta = document.getElementById('progressEta');
        const timelineActionContainer = document.getElementById('timelineActionContainer');
        const btnAddToTimeline = document.getElementById('btnAddToTimeline');
         const btnPaste = document.getElementById('btnPaste');
        const btnSettings = document.getElementById('btnSettings');
        const settingsModal = document.getElementById('settingsModal');
        const btnCloseSettings = document.getElementById('btnCloseSettings');
        const settingDownloadDir = document.getElementById('settingDownloadDir');
        const btnSaveSettings = document.getElementById('btnSaveSettings');
        
        const statusDot = document.getElementById('statusDot');
        const statusText = document.getElementById('statusText');

        let activeVideoData = null;
        let progressInterval = null;

        // Clipboard manual paste button helper
        btnPaste.addEventListener('click', async () => {
            try {
                const text = (await navigator.clipboard.readText() || "").trim();
                if (text) {
                    urlInput.value = text;
                }
            } catch (e) {
                console.error("Paste helper error:", e);
                alert("Please grant clipboard permissions or use Ctrl+V to paste.");
            }
        });

        // Resolve status poller
        async function checkResolveStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                if (data.resolve_connected) {
                    statusDot.classList.add('active');
                    statusText.textContent = "Natively Connected to Resolve API";
                    statusText.style.color = "var(--text-main)";
                } else {
                    statusDot.classList.remove('active');
                    statusText.textContent = "Resolve not open / API scripting disabled";
                    statusText.style.color = "var(--warning-color)";
                }
            } catch (e) {
                statusDot.classList.remove('active');
                statusText.textContent = "Lost server connection";
                statusText.style.color = "var(--danger-color)";
            }
        }
        
        setInterval(checkResolveStatus, 3000);
        checkResolveStatus();

        // Helper: Format duration (seconds -> MM:SS)
        function formatDuration(sec) {
            if (!sec) return '0:00';
            const m = Math.floor(sec / 60);
            const s = Math.floor(sec % 60).toString().padStart(2, '0');
            return `${m}:${s}`;
        }

        // Link analyzer/fetcher
        btnAnalyze.addEventListener('click', async () => {
            const url = urlInput.value.trim();
            if (!url) return;

            btnAnalyze.disabled = true;
            btnAnalyze.textContent = "Fetching...";
            videoCard.style.display = 'none';
            progressCard.style.display = 'none';

            try {
                const res = await fetch(`/api/fetch?url=${encodeURIComponent(url)}`);
                const result = await res.json();

                if (!result.success) {
                    alert("Error: " + result.error);
                    return;
                }

                activeVideoData = result.data;
                
                // Reset Download Button state for the new video
                btnDownload.disabled = false;
                btnDownload.textContent = "Download & Import to Resolve";
                
                // Populate UI Card using local safe hotlink-bypass proxy
                vidThumb.src = `/api/proxy-image?url=${encodeURIComponent(activeVideoData.thumbnail)}`;
                vidDuration.textContent = formatDuration(activeVideoData.duration);
                vidTitle.textContent = activeVideoData.title;
                vidAuthor.textContent = activeVideoData.uploader;
                
                // Badging
                vidPlatform.className = 'platform-badge';
                vidPlatform.textContent = activeVideoData.platform;
                if (activeVideoData.platform === 'youtube') {
                    vidPlatform.classList.add('badge-youtube');
                } else if (activeVideoData.platform === 'reddit') {
                    vidPlatform.classList.add('badge-reddit');
                } else if (activeVideoData.platform === 'instagram') {
                    vidPlatform.classList.add('badge-instagram');
                } else if (activeVideoData.platform === 'facebook') {
                    vidPlatform.classList.add('badge-facebook');
                } else if (activeVideoData.platform === 'twitter') {
                    vidPlatform.classList.add('badge-twitter');
                } else {
                    vidPlatform.classList.add('badge-video');
                }

                // Populate quality selector options
                resSelect.innerHTML = '';
                activeVideoData.resolutions.forEach(r => {
                    const opt = document.createElement('option');
                    opt.value = r.height;
                    opt.textContent = r.name;
                    resSelect.appendChild(opt);
                });
                
                // Set default to 1080p if available, else best
                const opt1080 = Array.from(resSelect.options).find(o => o.value == '1080');
                if (opt1080) {
                    resSelect.value = '1080';
                }

                videoCard.style.display = 'block';

            } catch (e) {
                alert("Failed to analyze. Please verify URL / check console.");
            } finally {
                btnAnalyze.disabled = false;
                btnAnalyze.textContent = "Fetch";
            }
        });

        // Download trigger
        btnDownload.addEventListener('click', async () => {
            if (!activeVideoData) return;

            const selectedHeight = resSelect.value;
            btnDownload.disabled = true;
            btnDownload.textContent = "Initializing...";
            timelineActionContainer.style.display = 'none';
            progressCard.style.display = 'block';

            try {
                const res = await fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        url: activeVideoData.url,
                        height: selectedHeight
                    })
                });
                
                const result = await res.json();
                if (!result.success) {
                    alert("Error: " + result.error);
                    btnDownload.disabled = false;
                    btnDownload.textContent = "Download & Import to Resolve";
                    return;
                }

                // Periodically poll download progress state
                if (progressInterval) clearInterval(progressInterval);
                progressInterval = setInterval(pollProgress, 500);

            } catch (e) {
                alert("Failed to start download task.");
                btnDownload.disabled = false;
                btnDownload.textContent = "Download & Import to Resolve";
            }
        });

        // Progress polling loop
        async function pollProgress() {
            try {
                const res = await fetch('/api/progress');
                const progress = await res.json();

                progressMsg.textContent = progress.message;
                progressPercent.textContent = progress.percent + "%";
                progressBarFill.style.width = progress.percent + "%";
                progressSpeed.textContent = progress.speed;
                progressEta.textContent = progress.eta;

                // Color themes depending on status
                if (progress.status === 'success') {
                    clearInterval(progressInterval);
                    progressPercent.style.color = "var(--success-color)";
                    progressBarFill.style.background = "var(--success-color)";
                    progressMsg.style.color = "var(--success-color)";
                    btnDownload.disabled = false;
                    btnDownload.textContent = "Done! Download Another";
                    timelineActionContainer.style.display = 'block';
                    
                    // Reset input field
                    urlInput.value = '';
                } else if (progress.status === 'warning') {
                    clearInterval(progressInterval);
                    progressPercent.style.color = "var(--warning-color)";
                    progressBarFill.style.background = "var(--warning-color)";
                    progressMsg.style.color = "var(--warning-color)";
                    btnDownload.disabled = false;
                    btnDownload.textContent = "Completed (Import Warning)";
                    alert("Download complete! Notice: Resolve API could not import it automatically. Please check that Resolve is open with External Scripting enabled, and import the file manually from your Downloads folder.");
                } else if (progress.status === 'error') {
                    clearInterval(progressInterval);
                    progressPercent.style.color = "var(--danger-color)";
                    progressBarFill.style.background = "var(--danger-color)";
                    progressMsg.style.color = "var(--danger-color)";
                    btnDownload.disabled = false;
                    btnDownload.textContent = "Failed. Try Again";
                    alert("Download Error: " + progress.error);
                }
            } catch (e) {
                console.error("Progress fetch issue:", e);
            }
        }

        btnAddToTimeline.addEventListener('click', async () => {
            btnAddToTimeline.disabled = true;
            btnAddToTimeline.textContent = "Appending to Timeline...";
            try {
                const res = await fetch('/api/add-to-timeline', { method: 'POST' });
                const result = await res.json();
                if (result.success) {
                    btnAddToTimeline.textContent = "Successfully Added!";
                    setTimeout(() => {
                        btnAddToTimeline.disabled = false;
                        btnAddToTimeline.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" class="feather feather-plus-circle"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="16"></line><line x1="8" y1="12" x2="16" y2="12"></line></svg> Add to Active Timeline`;
                    }, 2500);
                } else {
                    alert("Error: " + result.error);
                    btnAddToTimeline.disabled = false;
                    btnAddToTimeline.textContent = "Add to Active Timeline";
                }
            } catch (e) {
                alert("Failed to connect to server.");
                btnAddToTimeline.disabled = false;
                btnAddToTimeline.textContent = "Add to Active Timeline";
            }
        });

        // Load active settings from server
        async function loadSettings() {
            try {
                const res = await fetch('/api/settings');
                const data = await res.json();
                if (data.download_dir) {
                    settingDownloadDir.value = data.download_dir;
                }
            } catch (e) {
                console.error("Failed to load settings:", e);
            }
        }
        
        loadSettings();

        // Settings modal triggers
        btnSettings.addEventListener('click', () => {
            settingsModal.style.display = 'flex';
        });

        btnCloseSettings.addEventListener('click', () => {
            settingsModal.style.display = 'none';
        });

        settingsModal.addEventListener('click', (e) => {
            if (e.target === settingsModal) {
                settingsModal.style.display = 'none';
            }
        });

        btnSaveSettings.addEventListener('click', async () => {
            const path = settingDownloadDir.value.trim();
            if (!path) {
                alert("Please specify a valid downloads directory.");
                return;
            }
            btnSaveSettings.disabled = true;
            btnSaveSettings.textContent = "Saving...";
            try {
                const res = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ download_dir: path })
                });
                const result = await res.json();
                if (result.success) {
                    alert("Settings saved successfully!");
                    settingsModal.style.display = 'none';
                } else {
                    alert("Error: " + result.error);
                }
            } catch (e) {
                alert("Failed to save settings to server.");
            } finally {
                btnSaveSettings.disabled = false;
                btnSaveSettings.textContent = "Save Configuration";
            }
        });
    </script>
</body>
</html>
"""

# ==============================================================================
# MAIN EXECUTOR & CLI ROUTING
# ==============================================================================
def start_server(port):
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, DownloaderHandler)
    print(f"Resolve Downloader background server operational on port {port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    print("Server terminating.")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Resolve Downloader Service")
    parser.add_argument('--install', action='store_true', help="Install inside Resolve's script environment")
    parser.add_argument('--server', action='store_true', help="Boot backend server host")
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help="Port endpoint allocation")
    args = parser.parse_args()
    
    if args.install:
        install_plugin()
    elif args.server:
        start_server(args.port)
    else:
        # Standalone runner fallback
        # Let's check if the directory structure already has it. We can run server or install
        print("Resolve Downloader CLI interface.")
        print("To install as a native DaVinci Resolve Workflow Integration:")
        print("  python resolve_downloader.py --install")
        print("\nTo launch the standalone web server:")
        print("  python resolve_downloader.py --server")
        print("\nLaunching local test server on port 5533 for checking...")
        
        # Start server and open browser
        import webbrowser
        threading.Thread(target=start_server, args=(DEFAULT_PORT,), daemon=True).start()
        time.sleep(1)
        webbrowser.open(f"http://localhost:{DEFAULT_PORT}")
        
        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Terminating test environment.")
