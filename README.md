# 🌌 Resolve Downloader

> A premium, glassmorphic native Workflow Integration plugin for DaVinci Resolve that downloads video and audio from social media platforms and imports them directly into your active project with a single click.

---

## ✨ Features

* **💎 Universal Downloader Support**: Download high-quality video and audio natively from:
  * **YouTube** (Shorts, Standard videos)
  * **Reddit**
  * **Instagram** (Reels, Videos)
  * **Facebook**
  * **Twitter / X**
  * **Generic Video Formats**: Handles any media URL supported by `yt-dlp`!
* **⚡ Glassmorphic Dark-Mode Dashboard**: A jaw-dropping, semi-transparent user interface designed to feel like an organic, premium extension of DaVinci Resolve.
* **📥 Native DaVinci Resolve Importing**: Downloaded media is automatically named, sanitized, and imported directly into your active **Media Pool** silently in the background!
* **🎞️ Optional "Add to Active Timeline"**: Choose to instantly append imported clips to your currently active timeline with a single click after downloading.
* **📋 Smart Clipboard Paste Button**: A clean, icon-only clipboard button inside the input group lets you paste links instantly without intrusive auto-grabbing.
* **⚙️ Persistent Target Folder Selection**: Customize exactly where downloads are saved on your computer (e.g., `G:\Resolve Video Downloads`) via an interactive Settings modal. Settings persist across Resolve sessions!
* **🔤 Filename Sanitizer Engine**: Automatically strips emojis and non-ASCII characters from titles to prevent DaVinci Resolve import errors on Windows platforms.

---

## 🚀 Easy Installation Guide (Windows)

We have built a **one-click automated installer** to get you up and running in seconds!

1. **Download the Repository**: Click on the green `Code` button and select **Download ZIP**, then extract it.
2. **Run Installer**: Double-click the **`install.bat`** file inside the extracted folder.
   * *This will automatically verify Python, install required dependencies (`yt-dlp`), and register the workflow integration panel directly into DaVinci Resolve.*
3. **Open in Resolve**:
   * Restart your **DaVinci Resolve Studio** (Version 17 or higher).
   * Open the panel by navigating to:
     `Workspace -> Workflow Integrations -> Resolve Downloader`

---

## 🛠️ Manual Installation (Alternative)

If you prefer to install manually without running the batch script:

1. Install Python dependencies:
   ```bash
   pip install yt-dlp
   ```
2. Copy the following files from this repository:
   * `resolve_downloader.py`
   * `WorkflowIntegration.node`
3. Paste them into DaVinci Resolve's workflow integration directory:
   * **Windows Path**: `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Workflow Integration Plugins\com.antigravity.resolve.downloader\`
   * *Note: Create the final folder name exactly as shown if it does not exist.*
4. Restart DaVinci Resolve Studio and open the panel.

---

## 🎨 Premium UI Preview

Here is a glimpse of the gorgeous, native-feeling dark-mode glassmorphism interface running inside the Resolve workflow panel:

![Resolve Downloader UI](https://raw.githubusercontent.com/akzzy/Resolve-Downloader/main/downloader_loaded_1779176622710.png)

---

## 💡 Troubleshooting & Tips

* **DaVinci Resolve Studio Required**: Native Workflow Integration panels are an advanced API feature exclusive to **DaVinci Resolve Studio** (paid version). They do not load in the free version of DaVinci Resolve due to Blackmagic Design's integration limits.
* **Path Permission Denied**: If downloads fail or settings do not save, make sure your customized download directory has read/write permissions enabled.
* **Thumbnail Blocked Errors**: Certain websites like Instagram block hotlinking thumbnails. Resolve Downloader uses a built-in server-side image proxy to fetch and serve these images safely, ensuring zero broken icons.

---

## 📜 License & Open Source

This plugin is released completely free and open-source under the **MIT License**. Feel free to fork, customize, build pull requests, or share feedback!
