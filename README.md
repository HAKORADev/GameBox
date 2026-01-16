# GameBox - AI-Powered Web Games Platform

**Status: Discontinued / Open Source**  
*This project is no longer actively developed. Feel free to fork, modify, and continue development!*

## Overview

GameBox is an All-in-One Web Games Creation & Management Platform with AI-Powered Game Generation. It allows users to browse, create, and manage web-based games through an intuitive PyQt5 interface, featuring an integrated AI assistant (GAMAI) that helps with game creation and editing.

## Important Notice

**Development on this project has stopped.** This repository is now open source for the community to continue development, fix issues, or use as a reference for their own projects. I will not be making further updates or fixes to this codebase.

## Features

- **Web Games Browser** - Browse and play web-based games in an integrated browser
- **AI Game Generator (GAMAI)** - Create simple web games using natural language prompts
- **Game Editor** - Edit game HTML/CSS/JS with syntax highlighting and live preview
- **Favorites System** - Save and organize your favorite games
- **Customizable UI** - Dark/light themes and customizable settings
- **Cross-Platform** - Works on Windows, Linux, and macOS

## Known Issues and Limitations

If you plan to continue development, here are known issues that need attention:

### UI Issues

- **Text Visibility in Windows Dark Mode** - When running on Windows with dark mode enabled, some text elements may have poor contrast or appear unreadable. The application was primarily tested on Linux and some Windows-specific theming was not fully implemented. Fixing this would require updating the PyQt5 stylesheets to handle Windows dark mode properly.

### AI System Issues

- **GAMAI Uses Prompts Instead of LangChain** - The GAMAI AI assistant uses direct prompt engineering with Google's Gemini API rather than a proper LangChain integration. This means the AI responses are not structured, lack proper error handling, and the prompt templates are hardcoded as strings in the source code. For a more robust implementation, consider migrating to LangChain with structured output parsers.

- **Freezes During AI Generation** - The application freezes when GAMAI is generating a response or editing game code. This is because the AI operations run on the main GUI thread instead of a background thread. Any significant AI work will cause the interface to become unresponsive until completion. The fix involves moving all AI operations to QThread workers with proper signal/slot communication.

### Other Limitations

- **No Error Recovery** - If AI generation fails mid-way, there is no rollback mechanism and the partial game code may be corrupted
- **Limited Game Templates** - Only a few basic game templates exist; expanding this requires manual prompt engineering
- **No Game Sharing** - Generated games cannot be exported or shared with other users
- **Browser Limitations** - The integrated web browser has limited capabilities and may not support all web features

## For Developers

This project was abandoned mid-development. Below is information to help you get started if you want to continue development.

### Project Structure

```
GameBox/
├── src/                    # Source code directory
│   ├── gamebox.py         # Main application file (PyQt5 GUI)
│   └── requirements.txt   # Python dependencies
├── logo.png               # Application logo
├── app_icon.ico          # Application icon for Windows
├── gamebox.spec          # PyInstaller specification file
├── GameBox.exe           # Pre-built Windows executable
├── Instructions.txt      # Original user instructions
└── LICENSE               # MIT License
```

### Installation for Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/HAKORADev/GameBox.git
   cd GameBox
   ```

2. **Create a virtual environment (recommended)**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   cd src
   pip install -r requirements.txt
   ```

4. **Run the application**
   ```bash
   python gamebox.py
   ```

### Dependencies

The project requires the following Python packages:

- **PyQt5>=5.15.0** - Core GUI framework
- **PyQtWebEngine>=5.15.0** - Web browser component
- **keyboard>=0.13.5** - Keyboard input simulation
- **pyperclip>=1.8.2** - Clipboard operations
- **google-generativeai>=0.3.0** - Google Gemini AI integration
- **Pillow>=9.0.0** - Image processing
- **PyQt5-QScintilla>=2.14.0** - Code editor with syntax highlighting (optional, falls back gracefully)
- **pyinstaller>=6.0.0** - For building executables

### Building the Executable

To create a standalone executable:

```bash
cd src
pyinstaller --onefile --windowed --icon=../app_icon.ico --name=GameBox gamebox.py
```

Or use the included spec file:

```bash
pyinstaller gamebox.spec
```

The executable will be created in the `dist/` folder.

### Key Files and Components

- **gamebox.py** - Contains all GUI code, AI integration, and business logic (~850KB)
- **gamebox.spec** - PyInstaller configuration for building the Windows executable
- **logo.png** - Application logo used in the UI
- **app_icon.ico** - Icon file for the Windows executable

### AI Integration Notes

The GAMAI assistant uses Google's Gemini API directly. To configure AI features:

1. Get a free API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
2. The API key is typically stored in a config file or entered through the UI
3. The AI prompts are hardcoded in the source and can be modified there

### Contributing

Since this project is discontinued, the best way to contribute is to:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request
5. Or simply use the code as a reference for your own projects

## License

MIT License - See LICENSE file for details.

## Credits

Created by HAKORA. Built with PyQt5 and Google Gemini.

---

**Final Note:** This project represented an experiment in combining web browsing, game creation, and AI assistance. While development has stopped, the code is here for anyone who finds it useful. The community has made incredible projects from similar starting points, and this one is waiting for someone to give it new life!
