# GameBox v1.0.0 Stable Release

<div align="center">

![GameBox Logo](logo.png)

**Your All-in-One Game Creation & Management Platform**

[Features](#features) • [Controls](#controls) • [AI Setup](#ai-setup) • [Installation](#installation)

---

**Version:** 1.0.0 Stable  
**Release:** January 2026  
**Developer:** HAKORA

</div>

---

## 🎮 About GameBox

GameBox is a powerful, feature-rich game launcher and development platform that combines game library management with AI-powered creation tools. Whether you want to play existing HTML5 games, create new ones from scratch, or let AI generate unique games for you, GameBox has you covered.

This stable release represents months of development and testing, offering a robust solution for game enthusiasts and developers alike.

---

## ✨ Features

### 📚 Game Library Management

- **Organized Collection:** Browse all your games in a clean, intuitive interface
- **Grid & List Views:** Choose your preferred display mode
- **Smart Search:** Filter games by name, category, or tags
- **Category System:** Organize games with main categories (Action, Strategy, Puzzle, etc.) and sub-categories
- **Game Metadata:** Automatic tracking of playtime, edit count, and play frequency
- **Ratings & Feedback:** Rate games and add personal notes

### 🤖 AI-Powered Game Creation

GameBox integrates with Google Gemini AI to offer revolutionary game creation features:

- **One-Shot Creation:** Describe your game idea and let AI build it instantly
- **Surprise Me:** Get a random AI-generated game for inspiration
- **For You:** AI analyzes your existing games and creates something tailored to your tastes
- **AI Chat Assistant:** Get help with coding, game design, or troubleshooting

### 💻 Integrated Code Editor

- **Full Code Editor:** Edit game HTML/CSS/JavaScript directly within GameBox
- **Syntax Highlighting:** Color-coded code for better readability
- **Live Preview:** See changes instantly as you edit
- **Instant Editor Access:** Press F12 during gameplay for quick edits

### 📦 Import & Export

- **Import Games:** Bring in existing HTML5 games from your computer
- **Export Games:** Share your creations as ZIP files
- **ZIP Support:** Full ZIP file handling for game packages

### 🎯 User Experience

- **Fullscreen Modes:** Toggle between windowed and fullscreen for games (F1) or the app (F11)
- **Keyboard Navigation:** Navigate efficiently with keyboard shortcuts
- **Modern UI:** Clean, dark-themed interface that's easy on the eyes
- **Fast Loading:** Optimized performance for quick access to your games

---

## ⌨️ Controls

### Main Interface

| Key | Action |
|-----|--------|
| **Mouse Click** | Select buttons and games |
| **Arrow Keys** | Navigate through menus |
| **Scroll Wheel** | Cycle through options |
| **Enter** | Confirm selection |
| **Escape** | Return to previous menu / Exit app |

### Keyboard Shortcuts

| Key | Function |
|-----|----------|
| **F1** | Toggle Game Fullscreen/Windowed |
| **F10** | Open AI Chat Assistant |
| **F11** | Toggle App Fullscreen/Windowed |
| **F12** | Open Instant Editor (during gameplay) |

### Main Menu Buttons

| Button | Description |
|--------|-------------|
| **+ (Plus)** | Create new game or import from file |
| **Search** | Find and filter games |
| **Grid/List** | Toggle view mode |
| **AI** | Open GAMAI assistant menu |

---

## 🤖 AI Setup

GameBox features powerful AI integration using Google Gemini models. Follow these steps to enable AI features:

### Step 1: Get Your API Key

1. **Visit Google AI Studio:**
   ```
   https://aistudio.google.com/
   ```

2. **Sign In:** Use your Google account

3. **Create API Key:**
   - Click "Get API Key" in the left sidebar
   - Create a new API key for GameBox
   - **Copy the key immediately** (you can't view it again!)

### Step 2: Configure GameBox

1. Open GameBox
2. Press **F10** or click the **AI button** (🤖)
3. When prompted, paste your API key
4. Click Save

### Step 3: Test the AI

1. Open AI Chat (F10)
2. Send a test message
3. If you get a response, you're all set!

---

### 📊 Free Tier Information (2025)

| Model | Free Tier | Rate Limits |
|-------|-----------|-------------|
| **Gemini 2.5 Flash** | ✅ Yes | 15 RPM, 1M TPM, 1,500 RPD |
| **Gemini 2.5 Flash-Lite** | ✅ Yes | 15 RPM, 250K TPM, generous limits |
| **Gemini 2.5 Pro** | ❌ Paid | Not included in free tier |

**Recommendation:** Use **Gemini 2.5 Flash** or **Flash-Lite** for free access. Both offer excellent performance for game creation and coding assistance.

---

### 🔑 API Key Management

- Keep your API key private
- Don't share it publicly
- Generate new keys if compromised
- Monitor usage in Google AI Studio dashboard

---

## 📁 Installation

### System Requirements

- **Operating System:** Windows 10/11 (64-bit)
- **Processor:** Any modern x64 processor
- **Memory:** 4GB RAM minimum (8GB recommended)
- **Storage:** 200MB free space
- **Graphics:** DirectX 9 compatible GPU
- **Internet:** Required for AI features and online gaming

### Setup Instructions

1. **Extract the Folder:**
   - Right-click `GameBox_v1.0.0.zip`
   - Select "Extract All..."
   - Choose your desired location
   - Keep the "GameBox" folder intact

2. **Launch GameBox:**
   - Open the extracted `GameBox` folder
   - Double-click `GameBox.exe`
   - If Windows SmartScreen warns, click "More info" → "Run anyway"

3. **First Run:**
   - The app will create necessary folders automatically
   - Your games will be stored in `GameBox/Games/`
   - AI configuration is saved in `GameBox/GAMAI/`

### Directory Structure

After first launch:

```
GameBox/
├── GameBox.exe          # Main application
├── Games/               # Your game library (created automatically)
│   ├── GameName1/
│   ├── GameName2/
│   └── ...
├── GAMAI/               # AI configuration (created automatically)
│   └── config.json
└── exports/             # Exported games (created when you export)
```

---

## 🎯 Getting Started

### Creating Your First Game

1. Click the **+ (Plus)** button
2. Choose **"Create New Game"**
3. Enter game name and version
4. Select game type (2D/3D) and players (1/2)
5. Choose categories (up to 5 main categories)
6. Click Create
7. Start coding in the editor!

### Importing an Existing Game

1. Click the **+ (Plus)** button
2. Choose **"Import Game"**
3. Select an HTML file from your computer
4. Add metadata (name, version, categories)
5. Click Import

### Playing Games

1. Click on any game in your library
2. Choose **"Play"** from the options menu
3. Use **F1** for fullscreen
4. Press **F12** to edit while playing
5. Press **Escape** to return to menu

### Using AI Features

1. Press **F10** to open AI Chat
2. Ask questions, get coding help, or brainstorm ideas
3. For AI game creation:
   - Press **AI button** (🤖)
   - Choose creation method (One-Shot, Surprise, For You)
   - Follow the prompts

---

## 🔧 Troubleshooting

### Application Won't Start

**Issue:** GameBox crashes on launch (exit code 3)

**Solutions:**
1. Install Visual C++ Redistributable 2015-2022 (x64)
   - Download: https://aka.ms/vs/17/release/vc_redist.x64.exe
2. Run as Administrator
3. Temporarily disable antivirus software
4. Ensure Windows is up to date

### AI Features Not Working

**Issue:** Can't connect to AI or getting errors

**Solutions:**
1. Verify API key is correctly entered
2. Check internet connection
3. Ensure you're using a free-tier compatible model
4. Check rate limits in Google AI Studio

### Games Not Loading

**Issue:** Games fail to start or show errors

**Solutions:**
1. Ensure game has valid `index.html`
2. Check game folder permissions
3. Re-import the game
4. Verify game files aren't corrupted

### Slow Performance

**Issue:** App runs slowly or lags

**Solutions:**
1. Close unnecessary background programs
2. Reduce number of games in library
3. Use list view instead of grid view
4. Ensure adequate system resources

---

## 📝 Notes

### Privacy

- Your API key is stored locally only
- Game data stays on your computer
- No telemetry or data collection
- AI data processing follows Google's privacy policy

### Updates

- Check GitHub repository for updates
- Back up your `Games/` folder before updates
- Config files are preserved across updates

### Data Location

- **Games:** `GameBox/Games/`
- **AI Config:** `GameBox/GAMAI/config.json`
- **Exports:** `GameBox/exports/`
- **Backups:** Regularly backup these folders

---

## ⚖️ License

**NO LICENSE** - All rights reserved.

This software is provided as-is without any license. This means:

- ✅ You may use the software for personal use
- ❌ You may NOT redistribute without permission
- ❌ You may NOT modify the software
- ❌ You may NOT claim ownership
- ❌ You may NOT use commercially without permission

For permissions or inquiries, contact the developer.

---

## 📬 Contact

**Follow updates and development:**

- **X (Twitter):** [@HAKORAdev](https://x.com/HAKORAdev)

For bug reports, feature suggestions, or general inquiries, please reach out via X.

---

## 🙏 Acknowledgments

- **PyQt5** - Excellent GUI framework
- **Google Gemini** - Powerful AI capabilities
- **PyInstaller** - Reliable executable packaging
- **Open Source Community** - Inspiration and resources

---

<div align="center">

**Thank you for using GameBox!**

Built with ❤️ by HAKORA

</div>
