"""
GameBox
A game launcher that runs HTML5 games in an embedded browser using PyQt5.
"""

import sys
import os
import json
import threading
import random
import shutil
import collections
import zipfile
import tempfile
import string
from pathlib import Path
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QScrollArea, QMessageBox,
    QSizePolicy, QFrame, QInputDialog, QFileDialog, QDialog,
    QDialogButtonBox, QPlainTextEdit, QSplitter, QLineEdit,
    QTextEdit, QShortcut, QMenuBar, QMenu, QAction, QTextBrowser,
    QComboBox, QListWidget, QListWidgetItem, QGroupBox, QCheckBox, QRadioButton, QSpinBox,
    QAbstractItemView, QProgressDialog, QGraphicsOpacityEffect
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import Qt, QUrl, QSize, QTimer, pyqtSignal, QThread, QEvent, QRect, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QPixmap, QFont, QColor, QPainter, QKeySequence, QTextCursor, QTextFormat, QIcon

# Keyboard simulation and clipboard imports
import keyboard
import pyperclip
import time

# Syntax highlighting imports
try:
    from PyQt5.Qsci import QsciScintilla, QsciLexerHTML, QsciLexerCSS, QsciLexerJavaScript, QsciAPIs
    HAS_QSCINTILLA = True
except ImportError:
    HAS_QSCINTILLA = False
    print("Warning: QScintilla not available. Syntax highlighting will be disabled.")

# AI Integration imports
try:
    import google.generativeai as genai
    HAS_GEMINI_AI = True
except ImportError:
    HAS_GEMINI_AI = False
    print("Warning: Google Generative AI not available. AI features will be disabled.")

# Image processing imports
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    print("Warning: PIL (Pillow) not available. Vision features may be limited.")

# --- AI Selection Cache System ---
# Global variables to track the latest selected code for AI processing
_SELECTION_CACHE = {
    "selected_text": "",
    "start_line": 0,
    "end_line": 0,
    "editor_context": None  # To track which editor context (main/gameplay)
}

def cache_selection(text, start_line, end_line, editor_context):
    """Store selection to cache, replacing any previous selection"""
    global _SELECTION_CACHE
    _SELECTION_CACHE["selected_text"] = text
    _SELECTION_CACHE["start_line"] = start_line  
    _SELECTION_CACHE["end_line"] = end_line
    _SELECTION_CACHE["editor_context"] = editor_context
    print(f"Selection cached: {len(text)} chars from lines {start_line}-{end_line} ({editor_context})")

def get_cached_selection():
    """Get the currently cached selection"""
    global _SELECTION_CACHE
    return _SELECTION_CACHE

def clear_selection_cache():
    """Clear the selection cache"""
    global _SELECTION_CACHE
    _SELECTION_CACHE = {
        "selected_text": "",
        "start_line": 0,
        "end_line": 0,
        "editor_context": None
    }
    print("Selection cache cleared")

def create_gamai_model(use_backup=False):
    """Create and return a Gemini AI model instance with fallback capability
    
    Args:
        use_backup (bool): If True, use backup model (flash), if False use primary (pro)
    
    Returns:
        tuple: (model_instance, model_name) or (None, None) on error
    """
    if not HAS_GEMINI_AI:
        return None, None
    
    try:
        config = load_gamai_config()
        if not config.get('Key'):
            return None, None
        
        # Configure the API
        genai.configure(api_key=config['Key'])
        
        # Get model names from config
        primary_model = config.get('Model', 'gemini-2.5-pro')
        backup_model = config.get('BackupModel', 'gemini-2.5-flash')
        
        # Choose which model to use
        model_name = backup_model if use_backup else primary_model
        
        # Create and return the model
        model = genai.GenerativeModel(model_name)
        return model, model_name
        
    except Exception as e:
        print(f"Error creating AI model: {e}")
        return None, None

def switch_to_backup_model(current_model_name):
    """Switch to backup model (Flash) when rate limits are reached"""
    try:
        config = load_gamai_config()
        backup_model_name = config.get("BackupModel", "gemini-2.5-flash")
        
        if backup_model_name and backup_model_name != current_model_name:
            genai.configure(api_key=config.get("Key", ""))
            model = genai.GenerativeModel(backup_model_name)
            print(f"🔄 Switched from {current_model_name} to {backup_model_name} due to rate limits")
            return model, backup_model_name
            
    except Exception as e:
        print(f"Failed to switch to backup model: {e}")
    
    return None, current_model_name

def extract_content_from_code_blocks(ai_response):
    """Extract actual content from markdown code blocks in AI response
    
    Args:
        ai_response (str): AI response that may contain markdown code blocks
        
    Returns:
        str: Extracted content from code blocks, or original text if no blocks found
    """
    if not ai_response:
        return ""
    
    # Look for code blocks with various language specifications
    import re
    
    # Pattern to match markdown code blocks (```language or just ```)
    code_block_pattern = r'```(?:\w+)?\n(.*?)\n```'
    
    matches = re.findall(code_block_pattern, ai_response, re.DOTALL)
    
    if matches:
        # If we found code blocks, concatenate their content
        extracted_content = "\n".join(match.strip() for match in matches)
        return extracted_content
    
    # If no code blocks found, return the original response
    return ai_response.strip()

# --- 1. Category Constants ---

# Main Categories (Limited to 5 selections maximum)
MAIN_CATEGORIES = [
    "Action", "Strategy", "Puzzle", "Adventure", "Mystery", "Casual", "Racing", 
    "Simulation", "Sports", "RPG", "Shooter", "Story", "Sci-Fi", "Kids", 
    "Arcade", "Sandbox", "Experimental", "Party", "Tools", "Horror", 
    "Educational", "Music", "Art", "Social", "Economy", "War"
]

# Sub Categories (Unlimited selections)
SUB_CATEGORIES = [
    "Survival", "Platformer", "Fighting", "Open World", "Tactical", "Building", 
    "Driving", "Card Game", "Board", "Rhythm", "Anime", "Fantasy", "Medieval", 
    "Pixel", "Retro", "Minimal", "Hack'n'Slash", "Stealth", "Tower Defense", 
    "Multiplayer", "Singleplayer", "Co-op", "Competitive", "Turn-based", 
    "Real-time", "Roguelike", "Metroidvania", "Isometric", "Top-down", 
    "Side-scrolling", "First-person", "Third-person", "Indie", "AAA", 
    "Moddable", "Free-to-play", "Premium", "Demo", "Alpha", "Beta", 
    "Early Access", "VR", "AR", "Procedural", "Story-driven", "Open-ended", 
    "Linear", "Branching", "Sandbox", "Creative", "Puzzle-platformer"
]

# --- 2. AI Integration Constants ---

# AI Configuration
GAMAI_CONFIG_DIR = "GAMAI"
GAMAI_CONFIG_FILE = os.path.join(GAMAI_CONFIG_DIR, "config.json")

# Default AI Configuration
DEFAULT_AI_CONFIG = {
    "Key": "",
    "Model": "gemini-2.5-pro",
    "BackupModel": "gemini-2.5-flash",
    "Personas": {
        "Default": "You are GAMAI, the Gamebox assistant.",
        "OneShot": "",
        "Continues": "",
        "GameplayChat": "",
        "GameplayEdit": "",
        "EditorChat": "",
        "EditorEdit": ""
    }
}

# Available Gemini Models
GEMINI_MODELS = {
    "pro": "gemini-2.5-pro",
    "flash": "gemini-2.5-flash"
}

# AI Persona
GAMAI_PERSONA = """You are GAMAI, the Gamebox assistant with comprehensive tool capabilities across all contexts.

⚠️ CRITICAL RULE: When users ask "what tools do you have?", "what can you do?", "show me tools", "available tools", "list tools", "capabilities", or similar questions, you MUST immediately call the get_tools tool.

✅ CORRECT RESPONSE to tool questions:
```json
{"tool": "get_tools", "parameters": {}}
```

❌ NEVER make up tools or descriptions. Always use the actual get_tools tool.

TOOL SYSTEM OVERVIEW:
- Main Menu: open_game_play, open_game_editor, get_games_list
- Gameplay: edit_selected, edit_code  
- Editor: edit_selected, edit_code
- Global: get_tools (callable from anywhere)

MANDATORY RESPONSE PATTERN:
1. When asked about tools/capabilities → Call get_tools immediately
2. For game operations → Use open_game_play or open_game_editor with 'name' parameter
3. For AI code editing → Use edit_selected (highlighted code) or edit_code (full file or specific lines)

CURRENT CONTEXT-AWARE BEHAVIOR:
- Detect user's current mode (main menu, gameplay, or editor)
- Suggest relevant actions based on current context
- Provide helpful guidance for game development and editing
- Always prioritize calling get_tools when tool information is requested

🎯 REMEMBER: Never invent tools. Use get_tools tool to get accurate information!"""

# Global GAMAI Context Manager
class GamaiContextManager:
    """Manages dynamic global GAMAI context with 1M token limit management"""
    
    def __init__(self):
        self.global_context = []  # Single global context for all modes
        self.max_tokens = 1000000  # 1M tokens limit
        self.token_warning_threshold = 0.9  # Start pruning at 90% capacity
        self.current_mode = "main"  # Track current mode for context
        
    def get_context(self, context_name=None):
        """Get conversation history - always returns global context"""
        return self.global_context
    
    def set_context(self, context_name, history):
        """Set conversation history - clears and replaces global context"""
        self.global_context = history.copy()
        self._manage_token_limit()
    
    def add_message(self, context_name, role, content):
        """Add a message to global context with smart pruning"""
        message = {"role": role, "content": content}
        self.global_context.append(message)
        self._manage_token_limit()  # Check and manage token limit
    
    def clear_context(self, context_name=None):
        """Clear conversation history"""
        self.global_context = []
    
    def set_active_context(self, context_name):
        """Set the currently active context mode"""
        self.current_mode = context_name
    
    def get_active_context(self):
        """Get the currently active context name"""
        return self.current_mode
    
    def get_active_history(self):
        """Get conversation history for the active context"""
        return self.global_context
    
    def update_context_status(self, context_name, status_message):
        """Update context with user status (e.g., user opened game, exited game, etc.)"""
        status_msg = f"📍 User status: {status_message}"
        self.add_message("global", "system", status_msg)
    
    def add_game_context(self, context_name, game_name, game_path):
        """Add game information to global context"""
        try:
            # Read game files
            game_info = self._get_game_info(game_path)
            if game_info:
                game_msg = f"🎮 Game context: '{game_name}' loaded from '{game_path}'. {game_info}"
                self.add_message("global", "system", game_msg)
        except Exception as e:
            warning_msg = f"⚠️ Could not load game context for {game_name}: {e}"
            self.add_message("global", "system", warning_msg)
    
    def _get_game_info(self, game_path):
        """Extract information from game files (index.html, manifest.json) - includes ENTIRE file contents"""
        try:
            info_parts = []
            game_dir = Path(game_path)
            
            # Read index.html - ENTIRE CONTENT
            index_file = game_dir / "index.html"
            if index_file.exists():
                try:
                    with open(index_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip():
                            info_parts.append(f"📄 INDEX.HTML COMPLETE CONTENT:\n{content}")
                except Exception as e:
                    info_parts.append(f"📄 Error reading index.html: {e}")
            
            # Read manifest.json - ENTIRE CONTENT
            manifest_file = game_dir / "manifest.json"
            if manifest_file.exists():
                try:
                    with open(manifest_file, 'r', encoding='utf-8') as f:
                        manifest_content = f.read()
                        if manifest_content.strip():
                            info_parts.append(f"📋 MANIFEST.JSON COMPLETE CONTENT:\n{manifest_content}")
                except Exception as e:
                    info_parts.append(f"📋 Error reading manifest.json: {e}")
            
            return "\n\n".join(info_parts) if info_parts else "Game files loaded successfully."
        except Exception as e:
            return f"Game loaded (file read error: {e})"
    
    def _estimate_tokens(self, text):
        """Estimate token count for text - rough approximation"""
        # Simple token estimation: ~4 characters per token on average
        return len(text) // 4
    
    def _calculate_total_tokens(self):
        """Calculate total estimated tokens in global context"""
        total_tokens = 0
        for message in self.global_context:
            total_tokens += self._estimate_tokens(f"{message['role']}: {message['content']}")
        return total_tokens
    
    def _manage_token_limit(self):
        """Smart token management - implement sliding window approach for dynamic context"""
        total_tokens = self._calculate_total_tokens()
        
        if total_tokens <= self.max_tokens:
            return  # No action needed
        
        print(f"🧠 Managing token limit: {total_tokens}/{self.max_tokens} tokens")
        
        # Implement sliding window approach: 12345 → 23456 (remove oldest, keep newest)
        if total_tokens > self.max_tokens * self.token_warning_threshold:
            # Strategy 1: Remove oldest non-essential content first
            messages_to_remove = []
            tokens_to_remove = total_tokens - int(self.max_tokens * 0.7)  # Keep 70% buffer
            
            # Priority removal order:
            # 1. Oldest game file contents
            # 2. Old status/context messages  
            # 3. Old activity logs (but keep recent ones)
            # 4. Old user messages
            
            for i, message in enumerate(self.global_context):
                content = message.get('content', '')
                
                # Skip recent messages (last 20 messages are considered recent)
                if i >= len(self.global_context) - 20:
                    continue
                    
                # Remove priority 1: Old game file contents
                if ('INDEX.HTML COMPLETE CONTENT' in content or 
                    'MANIFEST.JSON COMPLETE CONTENT' in content):
                    message_tokens = self._estimate_tokens(content)
                    if tokens_to_remove >= message_tokens:
                        messages_to_remove.append(i)
                        tokens_to_remove -= message_tokens
                        continue
                
                # Remove priority 2: Old status messages (but keep activity logs)
                if (message['role'] == 'system' and 
                    '📝 Activity Log:' not in content and
                    'INDEX.HTML COMPLETE CONTENT' not in content and
                    'MANIFEST.JSON COMPLETE CONTENT' not in content):
                    message_tokens = self._estimate_tokens(content)
                    if tokens_to_remove >= message_tokens:
                        messages_to_remove.append(i)
                        tokens_to_remove -= message_tokens
                        continue
            
            # If still over limit, implement sliding window (remove oldest messages)
            current_tokens = self._calculate_total_tokens()
            while current_tokens > self.max_tokens * 0.8 and len(self.global_context) > 50:
                # Remove oldest message that's not activity log
                removed = False
                for i, message in enumerate(self.global_context):
                    content = message.get('content', '')
                    if '📝 Activity Log:' not in content:
                        self.global_context.pop(i)
                        removed = True
                        break
                
                if not removed:
                    break  # All remaining messages are activity logs
                    
                current_tokens = self._calculate_total_tokens()
            
            # Remove messages in reverse order
            for i in reversed(messages_to_remove):
                if i < len(self.global_context):  # Double check index is still valid
                    self.global_context.pop(i)
            
            # Add context management info
            self.global_context.append({
                "role": "system", 
                "content": f"📊 Context optimized: {self._calculate_total_tokens()}/{self.max_tokens} tokens"
            })
            
            print(f"✅ Context optimized: {self._calculate_total_tokens()}/{self.max_tokens} tokens")

# Global instance
GAMAI_CONTEXT = GamaiContextManager()

# --- 3. Category Validation Functions ---

def validate_categories(main_categories, sub_categories):
    """
    Validate categories against known lists and return validated vs unknown categories
    
    Args:
        main_categories: List of main category strings
        sub_categories: List of sub category strings
    
    Returns:
        tuple: (validated_main, unknown_main_count, validated_sub, unknown_sub_count)
    """
    # Validate main categories
    validated_main = []
    unknown_main_count = 0
    
    if main_categories:
        for category in main_categories:
            if category in MAIN_CATEGORIES:
                validated_main.append(category)
            else:
                unknown_main_count += 1
    
    # Validate sub categories
    validated_sub = []
    unknown_sub_count = 0
    
    if sub_categories:
        for category in sub_categories:
            if category in SUB_CATEGORIES:
                validated_sub.append(category)
            else:
                unknown_sub_count += 1
    
    return validated_main, unknown_main_count, validated_sub, unknown_sub_count

def format_categories_for_display(categories, category_type, known_categories):
    """
    Format categories for display with smart logic for nulls, unknowns, etc.
    
    Args:
        categories: List of category strings
        category_type: String "Main-Category" or "Sub-Category"
        known_categories: List of known valid categories for this type
    
    Returns:
        str: Formatted category string for display
    """
    if not categories:
        return f"{category_type}: null"
    
    # Filter out "null" strings and get only valid categories
    actual_categories = [cat for cat in categories if cat != "null" and cat.strip()]
    
    if not actual_categories:
        return f"{category_type}: null"
    
    validated_categories = []
    unknown_count = 0
    
    for category in actual_categories:
        if category in known_categories:
            validated_categories.append(category)
        else:
            unknown_count += 1
    
    # Format the result
    if validated_categories and unknown_count == 0:
        # Only valid categories
        if len(validated_categories) == 1:
            return f"{category_type}: {validated_categories[0]}"
        else:
            categories_str = ", ".join(validated_categories)
            return f"{category_type}: {categories_str}"
    elif not validated_categories and unknown_count > 0:
        # Only unknown categories
        if unknown_count == 1:
            return f"{category_type}: unknown"
        else:
            return f"{category_type}: other + {unknown_count}"
    else:
        # Mixed valid and unknown
        result = f"{category_type}: "
        if validated_categories:
            result += ", ".join(validated_categories)
        if unknown_count > 0:
            if validated_categories:
                result += ", "
            if unknown_count == 1:
                result += "unknown"
            else:
                result += f"other + {unknown_count}"
        return result

# --- 3. AI Configuration Management Functions ---

def ensure_gamai_config():
    """Ensure GAMAI config directory and file exist"""
    # Create GAMAI directory if it doesn't exist
    if not os.path.exists(GAMAI_CONFIG_DIR):
        os.makedirs(GAMAI_CONFIG_DIR)
    
    # Create config.json if it doesn't exist
    if not os.path.exists(GAMAI_CONFIG_FILE):
        with open(GAMAI_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_AI_CONFIG, f, indent=4, ensure_ascii=False)
    
    return True

def load_gamai_config():
    """Load GAMAI configuration from file"""
    try:
        ensure_gamai_config()
        with open(GAMAI_CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            # Ensure all required keys exist
            for key, value in DEFAULT_AI_CONFIG.items():
                if key not in config:
                    config[key] = value
            return config
    except Exception as e:
        print(f"Error loading GAMAI config: {e}")
        return DEFAULT_AI_CONFIG.copy()

def save_gamai_config(config):
    """Save GAMAI configuration to file"""
    try:
        ensure_gamai_config()
        with open(GAMAI_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving GAMAI config: {e}")
        return False

def update_gamai_key(new_key):
    """Update the API key in GAMAI config"""
    config = load_gamai_config()
    config['Key'] = new_key
    return save_gamai_config(config)

def is_gamai_configured():
    """Check if GAMAI is properly configured (has API key)"""
    config = load_gamai_config()
    return bool(config.get('Key', '').strip())

# --- 4. Data Model ---

class GameInfo:
    """Data class for game information with enhanced metadata"""
    
    def __init__(self, name, version, folder_path, icon_path=None, game_type="2D", players="1", main_categories=None, sub_categories=None, time_played=None, edits=None, played_times=None, rating=None, feedback=None):
        self.name = name if name else "Unknown Game"
        self.version = version if version else "N/A"
        self.type = game_type  # 2D or 3D
        self.players = players  # 1 or 2
        self.folder_path = folder_path
        self.icon_path = icon_path
        # Categories: Main (max 5), Sub (unlimited), default to None/null
        self.main_categories = main_categories if main_categories is not None else ["null", "null", "null"]
        self.sub_categories = sub_categories if sub_categories is not None else ["null", "null", "null"]
        # Auto-tracking fields - system only, user cannot modify
        self.time_played = time_played if time_played is not None else {"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0}
        self.edits = edits if edits is not None else 0
        self.played_times = played_times if played_times is not None else 0  # NEW: Auto-tracking for game launches
        # Rating field - 1-5 stars (None for unrated)
        self.rating = rating if rating is not None else None
        # Feedback field - array of feedback strings (max 10, system-only)
        self.feedback = feedback if feedback is not None else []
    
    def get_manifest_data(self):
        """Get complete manifest data including auto-tracking fields"""
        return {
            "name": self.name,
            "version": self.version,
            "type": self.type,        # NEW: Game type (2D/3D)
            "players": self.players,  # NEW: Number of players (1/2)
            "main_categories": self.main_categories if self.main_categories is not None else ["null", "null", "null"],  # NEW: Main categories (3 nulls if empty)
            "sub_categories": self.sub_categories if self.sub_categories is not None else ["null", "null", "null"],      # NEW: Sub categories (3 nulls if empty)
            # Auto-tracking fields - system only
            "time_played": self.time_played,      # Playtime tracking (minutes, hours, days, weeks, months)
            "edits": self.edits,                  # Edit count tracking
            "played_times": self.played_times,    # NEW: Game launch count tracking
            "rating": self.rating,                # NEW: Game rating (1-5 stars, None for unrated)
            "feedback": self.feedback,            # NEW: Feedback array (system-only, max 10 items)
            "icon": "icon.png" if self.icon_path else None,
            "created": datetime.now().isoformat()
        }
    
    @property
    def html_path(self):
        """Get full path to index.html"""
        return self.folder_path / "index.html"
    
    @property
    def manifest_path(self):
        """Get full path to manifest.json"""
        return self.folder_path / "manifest.json"
    
    def is_valid(self):
        """Check if game has required index.html file"""
        return self.html_path.exists()
    
    def update_metadata(self, game_type=None, players=None, main_categories=None, sub_categories=None):
        """Update game metadata fields"""
        if game_type and game_type in ["2D", "3D"]:
            self.type = game_type
        if players and players in ["1", "2"]:
            self.players = players
        # NEW: Update categories
        if main_categories is not None:
            self.main_categories = main_categories
        if sub_categories is not None:
            self.sub_categories = sub_categories
        
        # Save updated manifest
        self.save_manifest()
    
    def set_rating(self, rating):
        """Set game rating with validation (1-5 stars or None for unrated)"""
        if rating is None:
            self.rating = None
        elif isinstance(rating, int) and 1 <= rating <= 5:
            self.rating = rating
        else:
            raise ValueError("Rating must be an integer between 1-5 or None")
        # Save updated manifest
        self.save_manifest()
    
    def get_rating_display(self):
        """Get rating display string (stars or null)"""
        if self.rating is None:
            return "null"
        return "★" * self.rating
    
    def get_rating_text(self):
        """Get rating as text (e.g., "4/5" or "null")"""
        if self.rating is None:
            return "null"
        return f"{self.rating}/5"
    
    def get_feedback_count(self):
        """Get feedback count display (e.g., "2/10")"""
        return f"{len(self.feedback)}/10"
    
    def add_feedback(self, feedback_text):
        """Add feedback text to the game (max 10 feedbacks)"""
        if len(self.feedback) < 10 and feedback_text.strip():
            self.feedback.append(feedback_text.strip())
            self.save_manifest()
            return True
        return False
    
    def edit_feedback(self, index, new_feedback_text):
        """Edit feedback at specific index"""
        if 0 <= index < len(self.feedback) and new_feedback_text.strip():
            self.feedback[index] = new_feedback_text.strip()
            self.save_manifest()
            return True
        return False
    
    def delete_feedback(self, index):
        """Delete feedback at specific index"""
        if 0 <= index < len(self.feedback):
            del self.feedback[index]
            self.save_manifest()
            return True
        return False
    
    def save_manifest(self):
        """Save current game info to manifest.json"""
        try:
            with open(self.manifest_path, 'w', encoding='utf-8') as f:
                json.dump(self.get_manifest_data(), f, indent=4)
        except Exception as e:
            print(f"Error saving manifest: {e}")


# --- 2. Service Layer ---

class GameService:
    """Service for discovering and managing games"""
    
    def __init__(self, games_folder="Games"):
        # Use absolute path for consistency
        self.games_folder = Path(os.getcwd()) / games_folder
        self._ensure_games_folder()
    
    def _ensure_games_folder(self):
        """Create Games folder if it doesn't exist"""
        self.games_folder.mkdir(exist_ok=True)
    
    def discover_games(self):
        """Scan Games folder and return list of valid games"""
        games = []
        
        try:
            # Only iterate one level deep
            for game_folder in self.games_folder.iterdir():
                if game_folder.is_dir():
                    game_info = self._load_game(game_folder)
                    if game_info and game_info.is_valid():
                        games.append(game_info)
            
            # Sort by name
            games.sort(key=lambda g: g.name.lower())
            
        except Exception as e:
            # In a real app, this should be logged, but for a single file, a print is fine
            print(f"Error discovering games: {e}")
        
        return games
    
    def _load_game(self, game_folder):
        """Load game info from folder with enhanced metadata"""
        try:
            manifest_path = game_folder / "manifest.json"
            
            # Load or create manifest
            manifest = self._load_or_create_manifest(manifest_path, game_folder.name)
            
            # Ensure manifest is not None
            if manifest is None:
                print(f"Warning: Failed to load manifest for {game_folder}")
                return None
            
            name = manifest.get("name", game_folder.name) or game_folder.name
            version = manifest.get("version", "N/A") or "N/A"
            game_type = manifest.get("type", "2D")  # NEW: Read type, default to 2D
            players = manifest.get("players", "1")  # NEW: Read players, default to 1
            # NEW: Read categories from manifest (backward compatibility)
            main_categories = manifest.get("main_categories") or ["null", "null", "null"]  # NEW: Default to 3 nulls for old games
            sub_categories = manifest.get("sub_categories") or ["null", "null", "null"]      # NEW: Default to 3 nulls for old games
            # Auto-tracking fields - read from manifest with backward compatibility
            time_played = manifest.get("time_played") or {"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0}  # Default to 0 for old games
            edits = manifest.get("edits", 0) or 0  # Default to 0 for old games
            played_times = manifest.get("played_times", 0) or 0  # NEW: Default to 0 for old games
            rating = manifest.get("rating", None)  # NEW: Rating (1-5 or None for unrated)
            feedback = manifest.get("feedback") or []  # NEW: Feedback array (system-only, max 10 items)
            icon_file = manifest.get("icon", "icon.png")
            
            # Validate game_type and players
            if game_type not in ["2D", "3D"]:
                game_type = "2D"
            if players not in ["1", "2"]:
                players = "1"
            
            # Get icon path if exists (with null safety check)
            icon_path = None
            if icon_file:  # Ensure icon_file is not None
                icon_path = game_folder / icon_file
                icon_path = icon_path if icon_path.exists() else None
            
            return GameInfo(name, version, game_folder, icon_path, game_type=game_type, players=players, 
                          main_categories=main_categories, sub_categories=sub_categories, 
                          time_played=time_played, edits=edits, played_times=played_times, rating=rating, feedback=feedback)
            
        except Exception as e:
            print(f"Error loading game from {game_folder}: {e}")
            return None
    
    def _load_or_create_manifest(self, manifest_path, default_name):
        """Load manifest.json or create default"""
        if manifest_path.exists():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                # If loading fails, fall through to create default
                pass
        
        # Create default manifest with enhanced metadata
        default_manifest = {
            "name": default_name,
            "version": "1.0",
            "type": "2D",  # Default: 2D game
            "players": "1",  # Default: 1 player
            # Auto-tracking fields - system only, start with defaults
            "time_played": {"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0},
            "edits": 0,
            "played_times": 0,  # NEW: Game launch count tracking
            "icon": "icon.png",
            "created": datetime.now().isoformat()
        }
        
        try:
            # Write the default manifest back to the file
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(default_manifest, f, indent=4) # Use indent=4 for readability
        except Exception as e:
            print(f"Warning: Could not create manifest file at {manifest_path}. Error: {e}")
        
        return default_manifest
    
    def create_game(self, name, version, icon_data=None, game_type="2D", players="1", main_categories=None, sub_categories=None):
        """Create a new game folder with files"""
        try:
            print(f"\n{'='*60}")
            print(f"CREATING NEW GAME: {name} v{version}")
            print(f"{'='*60}")
            
            # Sanitize game name for folder creation
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not safe_name:
                safe_name = "game"
            
            game_folder = self.games_folder / safe_name
            print(f"Game folder path: {game_folder.absolute()}")
            print(f"Games folder: {self.games_folder.absolute()}")
            
            # Ensure games folder exists
            print(f"Creating games folder if not exists...")
            self.games_folder.mkdir(exist_ok=True)
            print(f"Games folder exists: {self.games_folder.exists()}")
            print(f"Games folder readable: {os.access(self.games_folder, os.R_OK)}")
            print(f"Games folder writable: {os.access(self.games_folder, os.W_OK)}")
            
            # Create game folder with conflict handling (same as import_game)
            print(f"Creating game folder: {game_folder}")
            if game_folder.exists():
                print(f"Game folder already exists - handling conflict")
                # Handle existing folder conflicts like import_game
                counter = 1
                while True:
                    new_name = f"{safe_name}_{counter}"
                    candidate_folder = self.games_folder / new_name
                    if not candidate_folder.exists():
                        game_folder = candidate_folder
                        # Update the safe_name for manifest
                        safe_name = new_name
                        break
                    counter += 1
                print(f"Using alternative folder name: {safe_name}")
            
            # Always create the folder (outside the if/else block like import_game)
            game_folder.mkdir(exist_ok=True)
            print(f"Game folder created: {game_folder.exists()}")
            print(f"Game folder readable: {os.access(game_folder, os.R_OK)}")
            print(f"Game folder writable: {os.access(game_folder, os.W_OK)}")
            
            # Create manifest.json with enhanced metadata
            print(f"\n--- CREATING MANIFEST.JSON ---")
            # For Surprise games, update the name to include counter suffix if conflict occurred
            display_name = name
            if safe_name != "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip():
                # Conflict occurred, use the updated name from safe_name
                display_name = safe_name.replace('_', ' ')  # Convert back to display format
                
            manifest = {
                "name": display_name,
                "version": version,
                "type": game_type,  # NEW: Game type (2D/3D)
                "players": players,  # NEW: Number of players (1/2)
                # NEW: Categories with null guidance (3 nulls for each)
                "main_categories": main_categories if main_categories is not None else ["null", "null", "null"],
                "sub_categories": sub_categories if sub_categories is not None else ["null", "null", "null"],
                # Auto-tracking fields - system only, start with defaults
                "time_played": {"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0},
                "edits": 0,
                "played_times": 0,  # NEW: Game launch count tracking
                "icon": "icon.png",
                "created": datetime.now().isoformat()
            }
            manifest_path = game_folder / "manifest.json"
            print(f"Manifest path: {manifest_path.absolute()}")
            print(f"Manifest folder permissions: {oct(os.stat(game_folder).st_mode)[-3:]}")
            
            try:
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, indent=4)
                print(f"✓ Manifest created successfully: {manifest_path.exists()}")
                
                # Verify manifest file
                if manifest_path.exists():
                    manifest_size = manifest_path.stat().st_size
                    print(f"  - File size: {manifest_size} bytes")
                    print(f"  - File readable: {os.access(manifest_path, os.R_OK)}")
                    print(f"  - File writable: {os.access(manifest_path, os.W_OK)}")
                else:
                    print("✗ ERROR: Manifest file does not exist after creation!")
                    
            except Exception as manifest_error:
                print(f"✗ ERROR creating manifest.json: {manifest_error}")
                raise manifest_error
            
            # Create default index.html
            print(f"\n--- CREATING INDEX.HTML ---")
            index_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{}</title>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            font-family: Arial, sans-serif;
            background-color: #2a2a2a;
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }}
        .container {{
            text-align: center;
        }}
        h1 {{
            color: #E5E5E5;
        }}
        .message {{
            margin: 20px 0;
            font-size: 18px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>{}</h1>
        <div class="message">
            Welcome to your new HTML5 game!<br>
            Start coding your game here...
        </div>
    </div>
</body>
</html>""".format(name, name)
            
            index_path = game_folder / "index.html"
            print(f"Index.html path: {index_path.absolute()}")
            print(f"HTML content length: {len(index_html)} characters")
            print(f"Game folder writable: {os.access(game_folder, os.W_OK)}")
            
            try:
                with open(index_path, 'w', encoding='utf-8') as f:
                    f.write(index_html)
                print(f"✓ Index.html created successfully: {index_path.exists()}")
                
                # Verify index.html file
                if index_path.exists():
                    index_size = index_path.stat().st_size
                    print(f"  - File size: {index_size} bytes")
                    print(f"  - File readable: {os.access(index_path, os.R_OK)}")
                    print(f"  - File writable: {os.access(index_path, os.W_OK)}")
                    
                    # Read back first few lines to verify content
                    with open(index_path, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                    print(f"  - First line: {first_line}")
                else:
                    print("✗ ERROR: index.html file does not exist after creation!")
                    
            except Exception as html_error:
                print(f"✗ ERROR creating index.html: {html_error}")
                import traceback
                traceback.print_exc()
                raise html_error
            
            # Create default icon.png
            print(f"\n--- CREATING ICON.PNG ---")
            icon_path = game_folder / "icon.png"
            print(f"Icon path: {icon_path.absolute()}")
            
            try:
                self._create_default_icon(icon_path)
                print(f"✓ Icon created: {icon_path.exists()}")
                
                # Verify icon file
                if icon_path.exists():
                    icon_size = icon_path.stat().st_size
                    print(f"  - File size: {icon_size} bytes")
                    print(f"  - File readable: {os.access(icon_path, os.R_OK)}")
                else:
                    print("✗ ERROR: Icon file does not exist after creation!")
                    
            except Exception as icon_error:
                print(f"✗ ERROR creating icon.png: {icon_error}")
                raise icon_error
            
            print(f"\n--- FINAL VERIFICATION ---")
            print(f"Game folder contents:")
            for file in game_folder.iterdir():
                print(f"  - {file.name} ({file.stat().st_size} bytes)")
            
            print(f"\n=== GAME CREATION COMPLETED SUCCESSFULLY ===")
            print(f"Game: {display_name} v{version}")
            print(f"Location: {game_folder.absolute()}")
            print(f"Files created: 3 (manifest.json, index.html, icon.png)")
            
            return GameInfo(display_name, version, game_folder, icon_path, game_type=game_type, players=players, 
                          main_categories=main_categories, sub_categories=sub_categories, 
                          time_played={"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0}, edits=0)
            
        except Exception as e:
            print(f"Error creating game: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _create_default_icon(self, icon_path):
        """Create a default game icon"""
        pixmap = QPixmap(200, 200)
        pixmap.fill(QColor(58, 58, 58))  # #3a3a3a
        
        painter = QPainter(pixmap)
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Arial", 48, QFont.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "+")
        painter.end()
        
        pixmap.save(str(icon_path))
    
    def import_game(self, html_content, name, version, main_categories=None, sub_categories=None):
        """Import a game from external HTML content"""
        try:
            print(f"\n{'='*60}")
            print(f"IMPORTING GAME: {name} v{version}")
            print(f"{'='*60}")
            
            # Sanitize game name for folder creation
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            if not safe_name:
                safe_name = "imported_game"
            
            game_folder = self.games_folder / safe_name
            print(f"Game folder path: {game_folder.absolute()}")
            
            # Ensure games folder exists
            self.games_folder.mkdir(exist_ok=True)
            
            # Handle existing folder conflicts
            if game_folder.exists():
                # Try to find a unique name
                counter = 1
                while True:
                    new_name = f"{safe_name}_{counter}"
                    candidate_folder = self.games_folder / new_name
                    if not candidate_folder.exists():
                        game_folder = candidate_folder
                        break
                    counter += 1
                print(f"Original folder name taken, using: {game_folder.name}")
            
            # Create game folder
            game_folder.mkdir(exist_ok=True)
            print(f"Game folder created: {game_folder.exists()}")
            
            # Create manifest.json with enhanced metadata
            print(f"\n--- CREATING MANIFEST.JSON ---")
            manifest = {
                "name": name,
                "version": version,
                "type": "2D",  # Default: 2D game for imported games
                "players": "1",  # Default: 1 player for imported games
                "main_categories": main_categories if main_categories is not None else ["null", "null", "null"],  # NEW: Main categories (3 nulls if empty)
                "sub_categories": sub_categories if sub_categories is not None else ["null", "null", "null"],      # NEW: Sub categories (3 nulls if empty)
                # Auto-tracking fields - system only, start with defaults
                "time_played": {"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0},
                "edits": 0,
                "played_times": 0,  # NEW: Game launch count tracking
                "icon": "icon.png",
                "created": datetime.now().isoformat()
            }
            manifest_path = game_folder / "manifest.json"
            
            try:
                with open(manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(manifest, f, indent=4)
                print(f"✓ Manifest created successfully: {manifest_path.exists()}")
                
            except Exception as manifest_error:
                print(f"✗ ERROR creating manifest.json: {manifest_error}")
                raise manifest_error
            
            # Create index.html with imported content
            print(f"\n--- IMPORTING INDEX.HTML ---")
            index_path = game_folder / "index.html"
            print(f"Index.html path: {index_path.absolute()}")
            print(f"HTML content length: {len(html_content)} characters")
            
            try:
                with open(index_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"✓ Index.html imported successfully: {index_path.exists()}")
                
                # Verify imported file
                if index_path.exists():
                    index_size = index_path.stat().st_size
                    print(f"  - File size: {index_size} bytes")
                    
                    # Read back first few lines to verify content
                    with open(index_path, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                    print(f"  - First line: {first_line[:50]}...")
                else:
                    print("✗ ERROR: index.html file does not exist after import!")
                    
            except Exception as html_error:
                print(f"✗ ERROR importing index.html: {html_error}")
                raise html_error
            
            # Create default icon.png
            print(f"\n--- CREATING ICON.PNG ---")
            icon_path = game_folder / "icon.png"
            print(f"Icon path: {icon_path.absolute()}")
            
            try:
                self._create_default_icon(icon_path)
                print(f"✓ Icon created: {icon_path.exists()}")
                
                # Verify icon file
                if icon_path.exists():
                    icon_size = icon_path.stat().st_size
                    print(f"  - File size: {icon_size} bytes")
                else:
                    print("✗ ERROR: Icon file does not exist after creation!")
                    
            except Exception as icon_error:
                print(f"✗ ERROR creating icon.png: {icon_error}")
                raise icon_error
            
            print(f"\n--- FINAL VERIFICATION ---")
            print(f"Game folder contents:")
            for file in game_folder.iterdir():
                print(f"  - {file.name} ({file.stat().st_size} bytes)")
            
            print(f"\n=== GAME IMPORT COMPLETED SUCCESSFULLY ===")
            print(f"Game: {name} v{version}")
            print(f"Location: {game_folder.absolute()}")
            print(f"Files created: 3 (manifest.json, index.html, icon.png)")
            
            return GameInfo(name, version, game_folder, icon_path, game_type="2D", players="1", 
                          main_categories=main_categories, sub_categories=sub_categories, 
                          time_played={"minutes": 0, "hours": 0, "days": 0, "weeks": 0, "months": 0}, edits=0)
            
        except Exception as e:
            print(f"Error importing game: {e}")
            import traceback
            traceback.print_exc()
            return None

    def delete_game(self, game_name):
        """Delete a game folder and all its contents"""
        try:
            print(f"\n{'='*60}")
            print(f"DELETING GAME: '{game_name}'")
            print(f"{'='*60}")
            
            # Clean up the game name - remove extra whitespace
            game_name_clean = game_name.strip()
            
            # Get all games to find the one to delete
            games = self.discover_games()
            game_to_delete = None
            
            # First try exact match (case insensitive, trimmed)
            for game in games:
                if game.name.strip().lower() == game_name_clean.lower():
                    game_to_delete = game
                    break
            
            # If exact match fails, try partial match for game names with extra whitespace
            if not game_to_delete:
                for game in games:
                    if game_name_clean.lower() in game.name.strip().lower() or game.name.strip().lower() in game_name_clean.lower():
                        game_to_delete = game
                        break
            
            if not game_to_delete:
                print(f"✗ ERROR: Game '{game_name_clean}' not found")
                print(f"Available games: {[g.name for g in games]}")
                return False
            
            # Get the game folder path
            game_folder = game_to_delete.folder_path
            print(f"Game folder path: {game_folder.absolute()}")
            print(f"Games folder: {self.games_folder.absolute()}")
            print(f"Found game to delete: '{game_to_delete.name}' at '{game_folder}'")
            
            # Check if the game folder exists
            if not game_folder.exists():
                print(f"✗ ERROR: Game folder does not exist: {game_folder}")
                return False
            
            print(f"Deleting game folder and all contents...")
            
            # Delete all files in the game folder
            import shutil
            shutil.rmtree(game_folder)
            
            # Verify the folder was deleted
            if game_folder.exists():
                print(f"✗ ERROR: Game folder still exists after deletion")
                return False
            
            print(f"\n--- FINAL VERIFICATION ---")
            print(f"Game '{game_to_delete.name}' deleted successfully")
            print(f"Location: {game_folder.absolute()} (now deleted)")
            
            print(f"\n=== GAME DELETION COMPLETED SUCCESSFULLY ===")
            print(f"Game: {game_to_delete.name}")
            
            return True
            
        except Exception as e:
            print(f"Error deleting game: {e}")
            import traceback
            traceback.print_exc()
            return False


# --- 2.1. Enhanced Context System Functions ---

def _format_file_with_line_numbers(content, filename=""):
    """
    Format file content with clear line numbers for AI context.
    
    Args:
        content (str): Raw file content
        filename (str): Name of the file for context
    
    Returns:
        str: Content with numbered lines in format [LINE 001]: actual_code
    """
    lines = content.split('\n')
    formatted_lines = []
    
    # Add file context header
    if filename:
        formatted_lines.append(f"=== FILE: {filename} ===")
        formatted_lines.append("Line numbers are in format [LINE XXX]: code_content")
        formatted_lines.append("When referencing lines, use format: lines X-Y or line X")
        formatted_lines.append("=" * 50)
    
    # Number each line with clear formatting
    for i, line in enumerate(lines, 1):
        line_num = f"{i:03d}"  # Zero-padded 3-digit line numbers
        formatted_lines.append(f"[LINE {line_num}]: {line}")
    
    return '\n'.join(formatted_lines)

def _load_enhanced_ai_context(game, selected_text="", start_line=0, end_line=0):
    """
    Load comprehensive AI context including manifest, index, and file content with line numbers.
    
    Args:
        game: Game object containing file paths and metadata
        selected_text (str): Currently selected text to edit
        start_line (int): Starting line of selection
        end_line (int): Ending line of selection
    
    Returns:
        dict: Comprehensive context for AI processing
    """
    context = {
        'game_info': {},
        'manifest_content': "",
        'index_content': "",
        'main_file_content': "",
        'main_file_with_lines': "",
        'selected_content': selected_text,
        'selection_info': {'start_line': start_line, 'end_line': end_line} if start_line > 0 else None
    }
    
    try:
        # Load game basic information
        if game:
            context['game_info'] = {
                'name': getattr(game, 'name', 'Unknown Game'),
                'html_path': str(game.html_path) if hasattr(game, 'html_path') else None,
                'game_dir': str(game.game_dir) if hasattr(game, 'game_dir') else None
            }
        
        # Load manifest file if available
        if game and hasattr(game, 'game_dir') and game.game_dir:
            manifest_path = game.game_dir / "manifest.json"
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        context['manifest_content'] = f.read()
                except Exception as e:
                    print(f"Warning: Could not load manifest.json: {e}")
            
            # Load index file if available
            index_path = game.game_dir / "index.json"
            if index_path.exists():
                try:
                    with open(index_path, 'r', encoding='utf-8') as f:
                        context['index_content'] = f.read()
                except Exception as e:
                    print(f"Warning: Could not load index.json: {e}")
        
        # Load main file content (HTML/Python/etc.)
        if game and hasattr(game, 'html_path') and game.html_path and game.html_path.exists():
            try:
                with open(game.html_path, 'r', encoding='utf-8') as f:
                    main_content = f.read()
                    context['main_file_content'] = main_content
                    context['main_file_with_lines'] = _format_file_with_line_numbers(
                        main_content, 
                        game.html_path.name if hasattr(game.html_path, 'name') else "main_file"
                    )
            except Exception as e:
                print(f"Warning: Could not load main file: {e}")
                context['main_file_content'] = "ERROR: Could not load main file content"
                context['main_file_with_lines'] = "ERROR: Could not load main file content"
    
    except Exception as e:
        print(f"Error loading enhanced AI context: {e}")
        context['error'] = str(e)
    
    return context

def _create_ai_context_prompt(context, edit_mode="edit_selected", toggle_mode="specific_lines"):
    """
    Create comprehensive AI prompt with enhanced context.
    
    Args:
        context (dict): Enhanced context from _load_enhanced_ai_context
        edit_mode (str): "edit_selected" or "edit_code"
        toggle_mode (str): "full_file" or "specific_lines"
    
    Returns:
        str: Formatted prompt for AI processing
    """
    prompt_parts = []
    
    # Header
    prompt_parts.append("=== AI CODE EDITING CONTEXT ===")
    
    # Game Information
    if context.get('game_info'):
        info = context['game_info']
        prompt_parts.append(f"Game: {info.get('name', 'Unknown')}")
        if info.get('html_path'):
            prompt_parts.append(f"Main File: {info.get('html_path')}")
    
    # Edit Mode and Toggle Instructions
    prompt_parts.append(f"Edit Mode: {edit_mode}")
    prompt_parts.append(f"Toggle Mode: {toggle_mode}")
    
    if toggle_mode == "full_file":
        prompt_parts.append("INSTRUCTIONS: Provide complete file content with your changes integrated.")
        prompt_parts.append("Response format: Return the entire file content with requested modifications.")
    else:
        prompt_parts.append("INSTRUCTIONS: Target specific line ranges for precise modifications.")
        prompt_parts.append("Response format: Specify line ranges like 'lines 5-10:' followed by new content.")
    
    # Manifest Context
    if context.get('manifest_content'):
        prompt_parts.append("\n=== MANIFEST ===")
        prompt_parts.append(context['manifest_content'])
    
    # Index Context  
    if context.get('index_content'):
        prompt_parts.append("\n=== INDEX ===")
        prompt_parts.append(context['index_content'])
    
    # File Content with Line Numbers
    if context.get('main_file_with_lines'):
        prompt_parts.append(f"\n=== MAIN FILE WITH LINE NUMBERS ===")
        prompt_parts.append(context['main_file_with_lines'])
        
        # Add selection info if available
        if context.get('selection_info'):
            sel_info = context['selection_info']
            prompt_parts.append(f"\nSELECTED CODE (Lines {sel_info['start_line']}-{sel_info['end_line']}):")
            if context.get('selected_content'):
                prompt_parts.append(context['selected_content'])
    
    # Recent Activity History
    try:
        recent_activities = []
        global_context = GAMAI_CONTEXT.get_context()
        
        # Get last 10 activity logs from global context
        for message in reversed(global_context):
            if message.get('role') == 'system' and '📝 Activity Log:' in message.get('content', ''):
                recent_activities.append(message['content'])
                if len(recent_activities) >= 10:  # Keep only last 10 activities
                    break
        
        if recent_activities:
            prompt_parts.append("\n=== RECENT EDITING ACTIVITY ===")
            for activity in reversed(recent_activities):  # Show oldest to newest
                prompt_parts.append(activity)
    except Exception as e:
        print(f"Warning: Could not load recent activity logs: {e}")
    
    # Specific Instructions for Line-Aware Editing
    prompt_parts.append("\n=== EDITING INSTRUCTIONS ===")
    if toggle_mode == "specific_lines":
        prompt_parts.append("- Use line numbers to target specific modifications")
        prompt_parts.append("- Reference lines as 'lines X-Y' or 'line X'")
        prompt_parts.append("- Preserve existing code structure and formatting")
        prompt_parts.append("- Only modify the specified line ranges")
    
    prompt_parts.append("\n" + "=" * 60)
    prompt_parts.append("Please analyze the context above and provide the requested code modifications.")
    prompt_parts.append("=" * 60)
    
    return '\n'.join(prompt_parts)

def _log_ai_edit_activity(operation_type, game_name, details):
    """
    Log AI editing activity for enhanced tracking.
    
    Args:
        operation_type (str): Type of operation (edit_selected, edit_code_full, edit_code_lines)
        game_name (str): Name of the game being edited
        details (dict): Operation details (lines, mode, etc.)
    """
    try:
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        log_entry = {
            'timestamp': timestamp,
            'operation_type': operation_type,
            'game_name': game_name,
            'details': details
        }
        
        # Create human-readable log message
        log_message = f"user edited game '{game_name}' using {operation_type} mode"
        if details.get('lines'):
            log_message += f" (lines {details['lines']})"
        
        # Add to global GAMAI context for AI awareness
        GAMAI_CONTEXT.add_message("global", "system", f"📝 Activity Log: {log_message}")
        
        # Print to console for debugging
        print(f"[AI EDIT LOG] {timestamp} | {operation_type} | Game: {game_name} | {details}")
        
        # TODO: Extend to file logging system in future implementation
        # log_file = "ai_edit_activity.log"
        # with open(log_file, 'a', encoding='utf-8') as f:
        #     f.write(json.dumps(log_entry) + '\n')
        
    except Exception as e:
        print(f"Warning: Could not log AI edit activity: {e}")

# --- 2.1. Dialog Classes ---

class AIEditCodeDialog(QDialog):
    """Dialog for AI-powered code editing of selected code"""
    
    def __init__(self, selected_text, start_line, end_line, game, editor_widget=None, toggle_mode="specific_lines", parent=None):
        super().__init__(parent)
        # Note: selected_text, start_line, end_line are not used in edit_code mode
        # but kept for backward compatibility
        self.selected_text = selected_text
        self.start_line = start_line
        self.end_line = end_line
        self.game = game
        self.editor_widget = editor_widget  # Editor widget for applying changes
        self.toggle_mode = toggle_mode  # "full_file" or "specific_lines"
        self.edited_code = None
        self.enhanced_context = None
        
        self.setWindowTitle("🤖 AI Code Editor")
        self.setModal(True)
        self.setFixedSize(650, 550)  # Slightly larger for toggle controls
        
        # Always use global context for seamless conversation
        self.conversation_history = GAMAI_CONTEXT.get_context("global")
        GAMAI_CONTEXT.set_active_context("global")
        
        self._setup_ui()
        
        # Load enhanced AI context
        self._load_enhanced_context()
    
    def _setup_ui(self):
        """Setup AI edit dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel("🤖 AI Code Editor")
        header_label.setStyleSheet("""
            QLabel {
                color: #E5E5E5;
                font-size: 18px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(header_label)
        
        # Toggle Mode Selection
        toggle_label = QLabel("Edit Mode:")
        toggle_label.setStyleSheet("font-weight: bold; margin-bottom: 5px; color: #CCCCCC;")
        layout.addWidget(toggle_label)
        
        toggle_layout = QHBoxLayout()
        
        # Full File Replace Toggle
        self.full_file_radio = QRadioButton("Full File Replace")
        self.full_file_radio.setStyleSheet("QRadioButton { color: #CCCCCC; font-size: 13px; }")
        self.full_file_radio.setChecked(self.toggle_mode == "full_file")
        self.full_file_radio.toggled.connect(self._on_toggle_changed)
        toggle_layout.addWidget(self.full_file_radio)
        
        # Specific Lines Replace Toggle
        self.specific_lines_radio = QRadioButton("Specific Lines Replace")
        self.specific_lines_radio.setStyleSheet("QRadioButton { color: #CCCCCC; font-size: 13px; }")
        self.specific_lines_radio.setChecked(self.toggle_mode == "specific_lines")
        self.specific_lines_radio.toggled.connect(self._on_toggle_changed)
        toggle_layout.addWidget(self.specific_lines_radio)
        
        toggle_layout.addStretch()
        layout.addLayout(toggle_layout)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("color: #E5E5E5; margin: 10px 0px;")
        layout.addWidget(separator)
        
        # User instruction
        instruction_label = QLabel("What would you like AI to do with this code?")
        instruction_label.setStyleSheet("font-weight: bold; margin: 10px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(instruction_label)
        
        self.instruction_input = QTextEdit()
        self.instruction_input.setPlaceholderText("Describe what you want AI to change, add, or improve in the selected code...")
        self.instruction_input.setMaximumHeight(100)
        self.instruction_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
                color: #CCCCCC;
            }
            QTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        layout.addWidget(self.instruction_input)
        
        # AI processed result preview
        result_label = QLabel("AI-Edited Result:")
        result_label.setStyleSheet("font-weight: bold; margin: 10px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(result_label)
        
        self.result_text_edit = QTextEdit()
        self.result_text_edit.setPlainText("AI result will appear here after processing...")
        self.result_text_edit.setMaximumHeight(150)
        self.result_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #333;
            }
        """)
        self.result_text_edit.setReadOnly(True)
        layout.addWidget(self.result_text_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.process_button = QPushButton("🤖 AI Process")
        self.process_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.process_button.clicked.connect(self._process_with_ai)
        button_layout.addWidget(self.process_button)
        
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px 20px;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.accept_button = QPushButton("✅ Apply Changes")
        self.accept_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.accept_button.clicked.connect(self.accept)
        self.accept_button.setEnabled(False)  # Enable only after AI processing
        button_layout.addWidget(self.accept_button)
        
        layout.addLayout(button_layout)
    
    def _load_enhanced_context(self):
        """Load enhanced AI context with manifest, index, and line numbers"""
        try:
            self.enhanced_context = _load_enhanced_ai_context(
                game=self.game,
                selected_text=self.selected_text,
                start_line=self.start_line,
                end_line=self.end_line
            )
            print(f"Enhanced context loaded for game: {self.enhanced_context.get('game_info', {}).get('name', 'Unknown')}")
        except Exception as e:
            print(f"Error loading enhanced context: {e}")
            self.enhanced_context = {}
    
    def _load_current_context(self):
        """Load current game manifest and file content for updated AI context"""
        try:
            # Load manifest.json if available
            if self.game and hasattr(self.game, 'game_file') and self.game.game_file:
                manifest_path = Path(self.game.game_file).with_name('manifest.json')
                if manifest_path.exists():
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        self.enhanced_context['manifest_content'] = f.read()
                else:
                    self.enhanced_context['manifest_content'] = ""
            else:
                self.enhanced_context['manifest_content'] = ""
            
            # Reload current file content from editor
            if self.editor_widget:
                try:
                    if hasattr(self.editor_widget, 'toPlainText'):
                        # QPlainTextEdit
                        current_content = self.editor_widget.toPlainText()
                    elif hasattr(self.editor_widget, 'text'):
                        # QTextEdit
                        current_content = self.editor_widget.text()
                    else:
                        # For other widget types, try to get content
                        current_content = ""
                        if hasattr(self.editor_widget, 'textCursor'):
                            cursor = self.editor_widget.textCursor()
                            current_content = cursor.document().toPlainText()
                    
                    self.enhanced_context['main_file_content'] = current_content
                    
                    # Add line-numbered version
                    if current_content:
                        from pathlib import Path
                        main_file_name = Path(self.game.game_file).name if hasattr(self.game, 'game_file') and self.game.game_file else "main_file"
                        self.enhanced_context['main_file_with_lines'] = self._format_file_with_line_numbers(current_content, main_file_name)
                    
                except Exception as e:
                    print(f"Warning: Error loading current file content: {e}")
                    self.enhanced_context['main_file_content'] = ""
                    self.enhanced_context['main_file_with_lines'] = ""
            
            print("✅ Loaded current context for AI: manifest + current file content")
            
        except Exception as e:
            print(f"Error loading current context: {e}")
            if 'manifest_content' not in self.enhanced_context:
                self.enhanced_context['manifest_content'] = ""
            if 'main_file_content' not in self.enhanced_context:
                self.enhanced_context['main_file_content'] = ""
            if 'main_file_with_lines' not in self.enhanced_context:
                self.enhanced_context['main_file_with_lines'] = ""
    
    def _format_file_with_line_numbers(self, content, file_name):
        """Format file content with line numbers for AI context"""
        try:
            lines = content.split('\n')
            numbered_lines = []
            for i, line in enumerate(lines, 1):
                numbered_lines.append(f"{i:4d}: {line}")
            return f"\n=== {file_name.upper()} ===\n" + '\n'.join(numbered_lines)
        except Exception as e:
            print(f"Error formatting file with line numbers: {e}")
            return f"\n=== {file_name.upper()} ===\n" + content
    
    def _on_toggle_changed(self):
        """Handle toggle mode changes"""
        if self.full_file_radio.isChecked():
            self.toggle_mode = "full_file"
        elif self.specific_lines_radio.isChecked():
            self.toggle_mode = "specific_lines"
        print(f"Toggle mode changed to: {self.toggle_mode}")
    
    def _process_with_ai(self):
        """Process the code editing request with AI"""
        instruction = self.instruction_input.toPlainText().strip()
        if not instruction:
            QMessageBox.warning(self, "No Instruction", "Please describe what you want AI to do with the selected code.")
            return
        
        try:
            # Disable process button during processing
            self.process_button.setEnabled(False)
            self.process_button.setText("🤖 Processing...")
            
            # Load current file context BEFORE AI processing (user's suggestion)
            self._load_current_context()
            
            # Create AI prompt for code editing
            prompt = self._create_ai_prompt(instruction)
            
            # Call AI to edit the code
            self._call_ai_for_code_edit(prompt)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process with AI: {e}")
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
    
    def _create_ai_prompt(self, instruction):
        """Create the AI prompt for code editing with enhanced context"""
        # Create comprehensive context prompt
        context_prompt = _create_ai_context_prompt(
            context=self.enhanced_context,
            edit_mode="edit_code",
            toggle_mode=self.toggle_mode
        )
        
        # Add user instruction
        user_instruction = f"\n\n=== USER REQUEST ===\n{instruction}\n"
        
        # Add mode-specific instructions
        if self.toggle_mode == "full_file":
            mode_instructions = """
RESPONSE FORMAT FOR FULL FILE MODE:
- Provide the COMPLETE file content with your changes integrated
- Include all existing code plus your modifications
- Maintain the entire file structure
- Do not use line number references in your response
- NO SPACING PRESERVATION COMMENTS - Return clean file content only
- Do not include any invisible comments like "<!--.-->", "/*.*/" at the start of your response
- Return the file exactly as it should appear in the editor

CRITICAL SPACING PRESERVATION INSTRUCTION:
- ❌ DO NOT use spacing preservation comments in full file mode
- ❌ DO NOT prefix the first line with "<!--.-->", "/*.*/" or any invisible comment
- Return clean, production-ready file content without any hidden characters
"""
        else:
            mode_instructions = """
RESPONSE FORMAT FOR SPECIFIC LINES MODE:
- Target specific line ranges for precise modifications
- Use format: "lines X-Y:" followed by the new content for that range
- Only modify the specified line ranges, preserve everything else
- Example response:
  lines 5-10:
    <new html content for lines 5-10>
  lines 15-18:
    <new css content for lines 15-18>

CRITICAL SPACING PRESERVATION INSTRUCTION:
- For HTML content: ALWAYS prefix the FIRST line after "lines X-Y:" with "<!--.-->"
- For CSS content: ALWAYS prefix the FIRST line after "lines X-Y:" with "/*.*/"
- For JavaScript content: ALWAYS prefix the FIRST line after "lines X-Y:" with "/*.*/"
- This invisible comment is essential for preserving leading spaces during copy/paste
- Example: lines 5-6:\n    <!--.-->     <div class='test'>\n        <p>content</p>
- The comment will be invisible but ensures all leading spaces are preserved
"""
        
        # Combine all parts
        full_prompt = context_prompt + user_instruction + mode_instructions
        return full_prompt
    
    def _call_ai_for_code_edit(self, prompt):
        """Call AI to edit the selected code"""
        try:
            # Create AI model instance
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                raise Exception("AI model not available")
            
            # Show current model being used
            self.process_button.setText(f"🤖 AI Processing ({model_name})...")
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                ai_response = response.text.strip()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name}, switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        raise Exception("Failed to switch to backup model")
                    
                    # Update button text to show backup model
                    self.process_button.setText(f"🤖 AI Processing ({backup_model_name})...")
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    ai_response = response.text.strip()
                else:
                    # Re-raise if it's not a rate limit error
                    raise rate_limit_error
            
            # Extract content from markdown code blocks if present
            extracted_content = extract_content_from_code_blocks(ai_response)
            
            # Set the result
            self.result_text_edit.setPlainText(ai_response)
            self.edited_code = extracted_content
            
            # Enable accept button
            self.accept_button.setEnabled(True)
            
            # Re-enable process button
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
            
            QMessageBox.information(self, "Success", "AI has processed your code. Review the result and click 'Apply Changes' to use it.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"AI processing failed: {e}")
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
    
    def get_edited_code(self):
        """Get the AI-edited code"""
        return self.edited_code
    
    def accept(self):
        """Apply the edited code back to the editor when dialog is accepted"""
        try:
            if self.edited_code and self.editor_widget:
                # Replace the entire content in the editor
                if hasattr(self.editor_widget, 'setPlainText'):
                    # QPlainTextEdit
                    self.editor_widget.setPlainText(self.edited_code)
                elif hasattr(self.editor_widget, 'setText'):
                    # QTextEdit
                    self.editor_widget.setText(self.edited_code)
                else:
                    # For other widget types, try to set content
                    if hasattr(self.editor_widget, 'textCursor'):
                        cursor = self.editor_widget.textCursor()
                        cursor.select(QTextCursor.Document)
                        cursor.insertText(self.edited_code)
                        self.editor_widget.setTextCursor(cursor)
            
            # Call parent accept to close the dialog
            super().accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply edited code: {e}")
    
    def _parse_ai_line_commands(self, ai_response):
        """Parse AI response to extract line-based commands
        
        Expected format:
        lines 12-13:
            background-color: yellow;
            color: black;
        lines 23-23:
            color: red;
        
        Returns: List of tuples (start_line, end_line, content)
        """
        import re
        
        line_commands = []
        
        try:
            print(f"🔍 DEBUG: Raw AI Response:\n{repr(ai_response)}")
            
            # Pattern to match "line X:" or "lines X-Y:" commands (both singular and plural)
            line_pattern = r'lines?\s+(\d+)(?:-(\d+))?\s*:'
            
            # Find all line commands in the response
            matches = re.finditer(line_pattern, ai_response, re.MULTILINE | re.IGNORECASE)
            
            for match_idx, match in enumerate(matches):
                start_line = int(match.group(1))
                end_line = int(match.group(2)) if match.group(2) else start_line
                
                print(f"🔍 DEBUG: Command {match_idx + 1}: Lines {start_line}-{end_line}")
                print(f"   Match text: {repr(match.group(0))}")
                print(f"   Match span: {match.span()} ({match.start()}-{match.end()})")
                
                # Find the content after this line command
                content_start = match.end()
                print(f"   Content starts at: {content_start}")
                
                # Find the next line command or end of string
                next_match = re.search(line_pattern, ai_response[content_start:], re.MULTILINE | re.IGNORECASE)
                
                if next_match:
                    content_end = content_start + next_match.start()
                    print(f"   Next command found at: {content_start + next_match.start()}")
                else:
                    content_end = len(ai_response)
                    print(f"   No next command, using end of string: {content_end}")
                
                # Extract the raw content between this command and the next
                raw_content = ai_response[content_start:content_end]
                
                # Enhanced content boundary detection: ensure we don't include partial commands
                # Check if raw_content starts with a new line and has content
                if raw_content.startswith('\n'):
                    raw_content = raw_content[1:]  # Remove leading newline
                    print(f"   Removed leading newline from raw content")
                elif raw_content.startswith(' \n'):
                    raw_content = raw_content[2:]  # Remove leading space+newline
                    print(f"   Removed leading space+newline from raw content")
                
                # If next_match exists, ensure we don't include any part of the next command
                if next_match:
                    # Look backwards from content_end to find the last meaningful newline
                    end_section = ai_response[max(0, content_end-100):content_end]
                    last_newline = end_section.rfind('\n')
                    if last_newline != -1:
                        # Adjust content_end to end at the last newline before next command
                        adjusted_end = content_end - (len(end_section) - last_newline)
                        raw_content = ai_response[content_start:adjusted_end]
                        print(f"   Adjusted content end to last newline: {adjusted_end}")
                
                print(f"   Final raw content ({len(raw_content)} chars): {repr(raw_content)}")
                print(f"   Raw content ({len(raw_content)} chars): {repr(raw_content)}")
                
                # Clean up the content: remove leading newlines and trailing whitespace
                content = raw_content.strip()
                print(f"   Stripped content: {repr(content)}")
                
                # Smart indentation removal - only remove common AI indentation (4-8 spaces)
                lines = content.split('\n')
                if lines and lines[0].strip():  # Only process if there's actual content
                    # Find the minimum indentation among non-empty lines
                    min_indent = float('inf')
                    for line in lines:
                        if line.strip():  # Non-empty line
                            leading_spaces = len(line) - len(line.lstrip())
                            if leading_spaces > 0:
                                min_indent = min(min_indent, leading_spaces)
                    
                    # Only remove common AI indentation (4-8 spaces), preserve code formatting and comment prefixes
                    if min_indent != float('inf') and 4 <= min_indent <= 8:
                        print(f"   Removing common indentation: {min_indent} spaces")
                        def preserve_comment_prefixes(line):
                            # Check if line starts with comment prefixes that should be preserved
                            if (line.startswith('/*.*/') or line.startswith('<!--.-->')):
                                # Preserve comment prefix, only remove indentation after the prefix
                                prefix_end = line.find('/*.*/') + 5 if line.startswith('/*.*/') else line.find('<!--.-->') + 8
                                content_start = prefix_end
                                # Find actual indentation (spaces after comment prefix)
                                content = line[content_start:]
                                if content and content[0] == ' ' and len(content) > min_indent:
                                    return line[:content_start] + content[min_indent:]
                                else:
                                    return line  # No indentation to remove
                            elif len(line) > min_indent and line.strip():
                                return line[min_indent:]
                            else:
                                return line
                        
                        lines = [preserve_comment_prefixes(line) for line in lines]
                        print(f"   ✅ Comment prefixes preserved after indentation removal")
                    else:
                        print(f"   Preserving original indentation (min_indent: {min_indent})")
                
                cleaned_content = '\n'.join(lines).strip()
                print(f"   Final cleaned content: {repr(cleaned_content)}")
                
                # REMOVED: HTML comment injection - now handled by AI with powerful prompt
                
                print(f"   ---")
                
                # Only add if there's actual content
                if cleaned_content:
                    line_commands.append((start_line, end_line, cleaned_content))
                else:
                    print(f"⚠️ Skipping empty content for lines {start_line}-{end_line}")
            
            print(f"🔍 Final parsed {len(line_commands)} line commands:")
            for start, end, content in line_commands:
                print(f"   Lines {start}-{end}: {repr(content[:100])}")
                
        except Exception as e:
            print(f"❌ Error parsing AI line commands: {e}")
            import traceback
            traceback.print_exc()
            line_commands = []
        
        return line_commands

    def _apply_fallback_specific_lines(self):
        """Fallback method when no line commands are found in AI response"""
        try:
            game_name = self.enhanced_context.get('game_info', {}).get('name', 'Unknown Game') if self.enhanced_context else 'Unknown'
            
            # Use original single line range replacement
            if self.editor_widget:
                if type(self.editor_widget).__name__ == 'QsciScintilla':
                    # QsciScintilla fallback
                    try:
                        line_from_0 = self.start_line - 1
                        line_to_0 = self.end_line - 1
                        self.editor_widget.setSelection(line_from_0, 0, line_to_0, 0)
                        # Use original method (now with AI comment preservation!)
                        self.editor_widget.replaceSelectedText(self.edited_code)
                        print(f"✅ Applied fallback replacement in QsciScintilla from lines {self.start_line}-{self.end_line} (AI comment method)")
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to replace lines {self.start_line}-{self.end_line}: {e}")
                        return False
                else:
                    # Text editor fallback
                    try:
                        cursor = self.editor_widget.textCursor()
                        cursor.movePosition(QTextCursor.Start)
                        for i in range(self.start_line - 1):
                            cursor.movePosition(QTextCursor.Down)
                        cursor.movePosition(QTextCursor.StartOfLine)
                        for i in range(self.end_line - self.start_line):
                            cursor.movePosition(QTextCursor.Down)
                        cursor.movePosition(QTextCursor.EndOfLine)
                        cursor.setPosition(cursor.anchor(), QTextCursor.KeepAnchor)
                        # Use original method (now with AI comment preservation!)
                        cursor.insertText(self.edited_code)
                        self.editor_widget.setTextCursor(cursor)
                        print(f"✅ Applied fallback replacement in text editor from lines {self.start_line}-{self.end_line} (AI comment method)")
                    except Exception as e:
                        QMessageBox.critical(self, "Error", f"Failed to replace lines {self.start_line}-{self.end_line}: {e}")
                        return False
            
            QMessageBox.information(self, "Success", f"AI has processed your code from lines {self.start_line}-{self.end_line}.")
            return True
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply fallback replacement: {e}")
            return False

    def _copy_content_to_clipboard(self, content):
        """Copy content to clipboard using pyperclip (preserves spaces)"""
        try:
            print(f"   📋 Copying content to clipboard: {repr(content[:50])}{'...' if len(content) > 50 else ''}")
            pyperclip.copy(content)
            return True
        except Exception as e:
            print(f"   ❌ Failed to copy to clipboard: {e}")
            return False

    def _simulate_paste(self):
        """Simulate Ctrl+V using keyboard library (preserves spacing like manual paste)"""
        try:
            print(f"   ⌨️ Simulating Ctrl+V paste")
            # Wait a small moment to ensure cursor is positioned
            time.sleep(0.1)
            # Send Ctrl+V to paste
            keyboard.send('ctrl+v')
            # Wait for paste operation to complete
            time.sleep(0.1)
            return True
        except Exception as e:
            print(f"   ❌ Failed to simulate paste: {e}")
            return False

    def _apply_keyboard_paste(self, content, focus_widget=None):
        """Apply content using keyboard-based clipboard approach (preserves spacing)"""
        try:
            print(f"   🎯 Using keyboard-based paste approach")
            
            # Step 1: Copy content to clipboard (preserves spaces)
            if not self._copy_content_to_clipboard(content):
                return False
                
            # Step 2: Ensure the editor widget is focused (if provided)
            if focus_widget and hasattr(focus_widget, 'setFocus'):
                focus_widget.setFocus()
                time.sleep(0.1)
                
            # Step 3: Simulate Ctrl+V paste operation (which preserves spacing)
            if not self._simulate_paste():
                return False
                
            print(f"   ✅ Keyboard paste completed successfully")
            return True
            
        except Exception as e:
            print(f"   ❌ Keyboard paste failed: {e}")
            return False

    def _apply_single_line_command(self, start_line, end_line, content):
        """Apply a single line command to the editor using delete-and-insert approach
        
        AI PROMPT-DRIVEN SPACING PRESERVATION:
        1. Delete ONLY the content of the line (not the newline)
        2. Position cursor at the beginning of that line
        3. Use replaceSelectedText() with AI-generated comment-prefixed content (preserves spacing)
        """
        try:
            print(f"🔧 DEBUG: Applying command lines {start_line}-{end_line} using delete-and-insert")
            print(f"   Content to insert: {repr(content)}")
            print(f"   🎯 Content ready for spacing preservation via AI comment")
            
            if type(self.editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: use delete-and-insert approach
                line_from_0 = start_line - 1
                line_to_0 = end_line - 1
                
                print(f"   QsciScintilla: Will delete content from line {line_from_0+1} to {line_to_0+1}")
                
                # For single line: delete only content, keep newline
                # For multiple lines: delete all content, keep structure
                target_line_text = self.editor_widget.text(line_from_0)
                print(f"   Target line {line_from_0}: {repr(target_line_text)}")
                
                if start_line == end_line:
                    # Single line: delete content only (not the newline)
                    if target_line_text.endswith('\n'):
                        content_to_delete = target_line_text[:-1]  # Remove newline
                    else:
                        content_to_delete = target_line_text
                    
                    print(f"   Will delete content only: {repr(content_to_delete)}")
                    
                    # Select from start to end (excluding newline)
                    self.editor_widget.setSelection(line_from_0, 0, line_from_0, len(content_to_delete))
                    print(f"   Selected content: {repr(self.editor_widget.selectedText())}")
                    
                    # Delete only the content
                    self.editor_widget.removeSelectedText()
                    print(f"   ✅ Content deleted, keeping line structure")
                    
                    # Step 2: Position cursor at start of line and paste content
                    # Set cursor at beginning of line
                    self.editor_widget.setSelection(line_from_0, 0, line_from_0, 0)
                    self.editor_widget.setCursorPosition(line_from_0, 0)
                    
                    # Use replaceSelectedText() with AI comment-prefixed content (now preserves spacing!)
                    self.editor_widget.replaceSelectedText(content)
                    print(f"   ✅ Pasted content at line {line_from_0+1} (AI comment method)")
                    
                else:
                    # Multiple lines: delete content from all lines
                    for line_num in range(line_from_0, line_to_0 + 1):
                        line_text = self.editor_widget.text(line_num)
                        if line_text.endswith('\n'):
                            content_to_delete = line_text[:-1]
                        else:
                            content_to_delete = line_text
                        
                        # Select and delete content only (not newline)
                        self.editor_widget.setSelection(line_num, 0, line_num, len(content_to_delete))
                        self.editor_widget.removeSelectedText()
                    
                    print(f"   ✅ Deleted content from lines {start_line}-{end_line}")
                    
                    # Position cursor at start of first line and paste
                    self.editor_widget.setSelection(line_from_0, 0, line_from_0, 0)
                    self.editor_widget.setCursorPosition(line_from_0, 0)
                    
                    # Use replaceSelectedText with HTML comment method
                    self.editor_widget.replaceSelectedText(content)
                    print(f"   ✅ Pasted content at line {start_line} (AI comment method)")
                
                return True
                
            else:
                # Text editor: use delete-and-insert approach
                print(f"   TextEditor: Using delete-and-insert for lines {start_line}-{end_line}")
                
                cursor = self.editor_widget.textCursor()
                
                if start_line == end_line:
                    # Single line: delete content only, keep newline
                    cursor.movePosition(QTextCursor.Start)
                    for i in range(start_line - 1):
                        cursor.movePosition(QTextCursor.Down)
                    
                    # Move to start of line
                    cursor.movePosition(QTextCursor.StartOfLine)
                    start_pos = cursor.position()
                    
                    # Move to end of line (but before newline)
                    cursor.movePosition(QTextCursor.EndOfLine)
                    end_pos = cursor.position()
                    
                    # If line has content, select it
                    if end_pos > start_pos:
                        cursor.setPosition(start_pos, QTextCursor.MoveAnchor)
                        cursor.setPosition(end_pos, QTextCursor.KeepAnchor)
                        
                        selected = cursor.selectedText()
                        print(f"   Selected content: {repr(selected)}")
                        
                        # Delete the content
                        cursor.removeSelectedText()
                        print(f"   ✅ Content deleted, keeping line structure")
                    
                    # Step 2: Position cursor at start of line and paste content
                    cursor.movePosition(QTextCursor.StartOfLine)
                    self.editor_widget.setTextCursor(cursor)
                    
                    # Use cursor.insertText() with HTML comment method (now preserves spacing!)
                    cursor.insertText(content)
                    self.editor_widget.setTextCursor(cursor)
                    print(f"   ✅ Pasted content at line {start_line} (AI comment method)")
                    
                else:
                    # Multiple lines: delete content from all lines
                    for line_num in range(start_line, end_line + 1):
                        cursor.movePosition(QTextCursor.Start)
                        for i in range(line_num - 1):
                            cursor.movePosition(QTextCursor.Down)
                        
                        cursor.movePosition(QTextCursor.StartOfLine)
                        start_pos = cursor.position()
                        
                        cursor.movePosition(QTextCursor.EndOfLine)
                        end_pos = cursor.position()
                        
                        if end_pos > start_pos:
                            cursor.setPosition(start_pos, QTextCursor.MoveAnchor)
                            cursor.setPosition(end_pos, QTextCursor.KeepAnchor)
                            cursor.removeSelectedText()
                    
                    print(f"   ✅ Deleted content from lines {start_line}-{end_line}")
                    
                    # Position cursor at start of first line
                    cursor.movePosition(QTextCursor.Start)
                    for i in range(start_line - 1):
                        cursor.movePosition(QTextCursor.Down)
                    cursor.movePosition(QTextCursor.StartOfLine)
                    self.editor_widget.setTextCursor(cursor)
                    
                    # Use cursor.insertText with HTML comment method
                    cursor.insertText(content)
                    self.editor_widget.setTextCursor(cursor)
                    print(f"   ✅ Pasted content at line {start_line} (AI comment method)")
                
                return True
                
        except Exception as e:
            print(f"❌ Error applying line command {start_line}-{end_line}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _apply_edited_code_with_toggle(self):
        """Apply edited code with toggle mode logic for AIEditCodeDialog"""
        try:
            if not self.edited_code:
                QMessageBox.warning(self, "No Code", "No edited code to apply.")
                return False
            
            # Log the operation
            game_name = self.enhanced_context.get('game_info', {}).get('name', 'Unknown Game') if self.enhanced_context else 'Unknown'
            
            if self.toggle_mode == "full_file":
                # Full file replacement mode
                _log_ai_edit_activity(
                    operation_type="edit_code_full",
                    game_name=game_name,
                    details={
                        'mode': 'full_file',
                        'lines_modified': 'entire_file',
                        'original_length': len(self.enhanced_context.get('main_file_content', '')),
                        'new_length': len(self.edited_code)
                    }
                )
                
                if self.editor_widget:
                    # Replace entire content in the editor
                    if hasattr(self.editor_widget, 'setPlainText'):
                        # QPlainTextEdit
                        self.editor_widget.setPlainText(self.edited_code)
                    elif hasattr(self.editor_widget, 'setText'):
                        # QTextEdit
                        self.editor_widget.setText(self.edited_code)
                    else:
                        # For other widget types, try to set content
                        if hasattr(self.editor_widget, 'textCursor'):
                            cursor = self.editor_widget.textCursor()
                            cursor.select(QTextCursor.Document)
                            cursor.insertText(self.edited_code)
                            self.editor_widget.setTextCursor(cursor)
                
                QMessageBox.information(self, "Success", "Full file has been replaced with AI-generated content.")
                return True
                
            else:
                # Specific lines replacement mode - use AI line commands parser
                line_commands = self._parse_ai_line_commands(self.edited_code)
                
                if not line_commands:
                    # Enhanced detection for non-command AI responses
                    ai_response = self.edited_code.strip()
                    
                    # Check if this looks like a conversational response (not code commands)
                    is_conversational = (
                        # Looks like AI is talking/explaining rather than giving commands
                        any(phrase in ai_response.lower() for phrase in [
                            "here's", "here is", "you can", "you should", "i suggest", 
                            "i recommend", "let me", "i'll", "i would", "try this",
                            "to improve", "to fix", "you might", "consider", "instead"
                        ]) or
                        # Very short responses (likely conversational)
                        len(ai_response) < 50 or
                        # Responses that don't look like code
                        not any(char in ai_response for char in ['{', '}', '(', ')', ';', '=', '<', '>', ':', '"', "'"]) or
                        # Responses that mention line numbers without proper format
                        ('line' in ai_response.lower() and 'lines' not in ai_response.lower() and ':' not in ai_response)
                    )
                    
                    if is_conversational:
                        print(f"🤖 Detected conversational AI response (no line commands)")
                        print(f"   Response preview: {ai_response[:100]}{'...' if len(ai_response) > 100 else ''}")
                        
                        # Ask user how they want to handle this
                        reply = QMessageBox.question(
                            self,
                            "AI Response Without Commands",
                            "🤖 AI responded conversationally without using line commands.\n\n"
                            f"Response preview:\n{ai_response[:200]}{'...' if len(ai_response) > 200 else ''}\n\n"
                            "How would you like to proceed?\n"
                            "• Yes - Use full file replacement mode\n"
                            "• No - Cancel and ask AI to use 'lines X-Y:' format",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No
                        )
                        
                        if reply == QMessageBox.Yes:
                            # Temporarily switch to full file mode for this response
                            print("🔄 User chose to use full file replacement for conversational AI response")
                            self.toggle_mode = "full_file"
                            return self._apply_edited_code_with_toggle()
                        else:
                            print("❌ User chose to cancel - AI should use line commands")
                            QMessageBox.information(
                                self, 
                                "AI Response Format",
                                "Please ask the AI to use the 'lines X-Y:' format for specific line modifications.\n\n"
                                "Example:\n"
                                "lines 12-13:\n"
                                "    background-color: yellow;\n"
                                "lines 23-23:\n"
                                "    color: red;"
                            )
                            return False
                    else:
                        # Fallback: if no line commands found but doesn't look conversational, treat as single replacement
                        print("⚠️ No line commands found in AI response, using fallback method")
                        return self._apply_fallback_specific_lines()
                
                # Log the operation with multiple line modifications
                _log_ai_edit_activity(
                    operation_type="edit_code_specific_lines",
                    game_name=game_name,
                    details={
                        'mode': 'specific_lines',
                        'line_commands_count': len(line_commands),
                        'line_ranges': [f"{start}-{end}" for start, end, _ in line_commands]
                    }
                )
                
                if self.editor_widget:
                    # Apply line commands in reverse order to avoid line number shifts
                    success_count = 0
                    failed_commands = []
                    
                    # Sort by line number in descending order (bottom to top)
                    sorted_commands = sorted(line_commands, key=lambda x: x[0], reverse=True)
                    
                    for start_line, end_line, content in sorted_commands:
                        try:
                            success = self._apply_single_line_command(start_line, end_line, content)
                            if success:
                                success_count += 1
                                print(f"✅ Applied line command: lines {start_line}-{end_line}")
                            else:
                                failed_commands.append(f"{start_line}-{end_line}")
                        except Exception as e:
                            print(f"❌ Failed to apply line command {start_line}-{end_line}: {e}")
                            failed_commands.append(f"{start_line}-{end_line}")
                    
                    # Show results
                    if failed_commands:
                        QMessageBox.warning(self, "Partial Success", 
                                          f"Applied {success_count}/{len(line_commands)} line commands.\n"
                                          f"Failed: {', '.join(failed_commands)}")
                    else:
                        QMessageBox.information(self, "Success", 
                                              f"AI has successfully applied {success_count} line modifications.")
                    return len(failed_commands) == 0
                else:
                    QMessageBox.warning(self, "No Editor", "No editor widget available for applying changes.")
                    return False
                
        except Exception as e:
            game_name = self.enhanced_context.get('game_info', {}).get('name', 'Unknown Game') if self.enhanced_context else 'Unknown'
            QMessageBox.critical(self, "Error", f"Failed to apply edited code: {e}")
            _log_ai_edit_activity(
                operation_type="edit_code_error",
                game_name=game_name,
                details={'error': str(e), 'mode': self.toggle_mode}
            )
            return False

    def accept(self):
        """Enhanced accept method with toggle mode support"""
        # Use the new toggle-aware application method
        success = self._apply_edited_code_with_toggle()
        
        if success:
            # Log AI edit activity
            self._log_ai_edit_activity()
            # Call parent accept to close the dialog
            super().accept()
        # If failed, the _apply_edited_code_with_toggle method already shows error dialog
    
    def _log_ai_edit_activity(self):
        """Log AI edit activity for enhanced context awareness"""
        try:
            edit_type = "edit_code"
            mode_desc = ""
            
            if self.toggle_mode == "full_file":
                mode_desc = "full_file"
            elif self.toggle_mode == "specific_lines":
                # For specific_lines mode, we already have detailed logging in _apply_edited_code_with_toggle
                mode_desc = "specific_lines (AI processed line commands)"
            
            log_entry = f"user edited game '{self.game.name}' using {edit_type} {mode_desc}"
            
            # Add to global GAMAI context for AI awareness
            GAMAI_CONTEXT.add_message("global", "system", f"📝 Activity Log: {log_entry}")
            
            # Print to console
            print(f"📝 Activity Log: {log_entry}")
            
            # Also add via parent method if available
            if hasattr(self.parent(), 'add_activity_log'):
                self.parent().add_activity_log(log_entry)
                
        except Exception as e:
            print(f"Error logging AI edit activity: {e}")


class AIEditionPopup(QDialog):
    """Popup for AI editing with two modes: Edit Code and Edit Selected"""
    
    def __init__(self, editor_widget=None, game=None, parent=None):
        super().__init__(parent)
        self.editor_widget = editor_widget
        self.game = game
        self.selected_text = ""
        self.start_line = 0
        self.end_line = 0
        self.edition_mode = None  # "edit_code" or "edit_selected"
        self.edited_code = None
        
        self.setWindowTitle("🤖 AI Code Editor")
        self.setModal(True)
        self.setFixedSize(500, 400)
        self._setup_ui()
        
        # Check initial selection state
        self._check_selection_state()
    
    def _get_text_cursor(self, editor_widget):
        """Get text cursor from editor widget, handling both QPlainTextEdit and QsciScintilla"""
        if editor_widget is None:
            return None
            
        # Check if it's a QsciScintilla (has different methods)
        if hasattr(editor_widget, 'sendSelectionChanged'):
            # QsciScintilla doesn't have textCursor(), use its selection methods
            return editor_widget
        else:
            # QPlainTextEdit and similar widgets
            return editor_widget.textCursor()
    
    def _get_selected_text(self, editor_widget):
        """Get selected text from editor widget, handling both QPlainTextEdit and QsciScintilla"""
        if editor_widget is None:
            return "", 0, 0
            
        try:
            # Check if it's a QsciScintilla using type comparison
            if type(editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: get selection using its methods
                if editor_widget.hasSelectedText():
                    selected_text = editor_widget.selectedText()
                    # For QsciScintilla, get line numbers differently
                    line_from, index_from, line_to, index_to = editor_widget.getSelection()
                    start_line = line_from + 1
                    end_line = line_to + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
            else:
                # QPlainTextEdit and similar widgets
                cursor = editor_widget.textCursor()
                if cursor.hasSelection():
                    selected_text = cursor.selectedText()
                    start_line = cursor.blockNumber() + 1
                    end_line = cursor.blockNumber() + 1
                    if cursor.selectionEnd() != cursor.selectionStart():
                        # Multi-line selection
                        temp_cursor = QTextCursor(cursor)
                        temp_cursor.setPosition(cursor.selectionEnd())
                        end_line = temp_cursor.blockNumber() + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
        except Exception as e:
            print(f"Error getting selected text: {e}")
            return "", 0, 0
    
    def _has_selection(self, editor_widget):
        """Check if editor widget has text selected"""
        if editor_widget is None:
            return False
            
        try:
            # Check if it's a QsciScintilla using type comparison
            if type(editor_widget).__name__ == 'QsciScintilla':
                return editor_widget.hasSelectedText()
            else:
                # QPlainTextEdit and similar widgets
                cursor = editor_widget.textCursor()
                return cursor.hasSelection()
        except Exception as e:
            print(f"Error checking selection: {e}")
            return False

    def _setup_ui(self):
        """Setup the AI edition popup UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
        # Header
        header_label = QLabel("🤖 AI Code Editor")
        header_label.setStyleSheet("""
            QLabel {
                color: #E5E5E5;
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 15px;
            }
        """)
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Mode selection buttons
        mode_label = QLabel("Choose editing mode:")
        mode_label.setStyleSheet("font-weight: bold; margin-bottom: 10px; color: #CCCCCC;")
        layout.addWidget(mode_label)
        
        # Button container
        button_container = QWidget()
        button_layout = QVBoxLayout(button_container)
        button_layout.setSpacing(15)
        
        # Edit Code button
        self.edit_code_button = QPushButton("📝 Edit Code")
        self.edit_code_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                padding: 20px;
                font-size: 16px;
                font-weight: bold;
                text-align: left;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.edit_code_button.clicked.connect(self._open_edit_code_mode)
        button_layout.addWidget(self.edit_code_button)
        
        # Edit Selected button
        self.edit_selected_button = QPushButton("✂️ Edit Selected Lines")
        self.edit_selected_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                padding: 20px;
                font-size: 16px;
                font-weight: bold;
                text-align: left;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.edit_selected_button.clicked.connect(self._open_edit_selected_mode)
        button_layout.addWidget(self.edit_selected_button)
        
        layout.addWidget(button_container)
        
        # Selection status
        self.selection_status_label = QLabel()
        self.selection_status_label.setStyleSheet("color: #666; font-size: 12px; margin-top: 10px;")
        layout.addWidget(self.selection_status_label)
        
        # Cancel button
        cancel_layout = QHBoxLayout()
        cancel_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px 20px;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        cancel_layout.addWidget(self.cancel_button)
        
        layout.addLayout(cancel_layout)
    
    def _check_selection_state(self):
        """Check for cached selection first, then fall back to current selection"""
        # First, try to use cached selection
        cache_data = get_cached_selection()
        if cache_data["selected_text"] and cache_data["selected_text"].strip():
            self.selected_text = cache_data["selected_text"]
            self.start_line = cache_data["start_line"]
            self.end_line = cache_data["end_line"]
            
            self.edit_selected_button.setEnabled(True)
            self.edit_selected_button.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                    border: 2px solid #E5E5E5;
                    border-radius: 8px;
                    padding: 20px;
                    font-size: 16px;
                    font-weight: bold;
                    text-align: left;
                    color: white;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                    border: 2px solid #E5E5E5;
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                    border: 2px solid #E5E5E5;
                }
            """)
            self.selection_status_label.setText(f"✅ Using cached selection ({len(self.selected_text)} characters, lines {self.start_line}-{self.end_line})")
            return
        
        # If no cached selection, check current selection in editor
        if not self.editor_widget:
            self.edit_selected_button.setEnabled(False)
            self.edit_selected_button.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #333333, stop:1 #2a2a2a);
                    border: 2px solid #555555;
                    border-radius: 8px;
                    padding: 20px;
                    font-size: 16px;
                    font-weight: bold;
                    text-align: left;
                    color: #E5E5E5;
                }
                QPushButton:disabled {
                    background-color: #2a2a2a;
                    border: 2px solid #555555;
                    color: #E5E5E5;
                }
            """)
            self.selection_status_label.setText("❌ No cached selection available - Select code and press F9 to cache it")
            return
        
        try:
            # Use the helper methods to handle both QPlainTextEdit and QsciScintilla
            if self._has_selection(self.editor_widget):
                selected_text, start_line, end_line = self._get_selected_text(self.editor_widget)
                self.selected_text = selected_text
                self.start_line = start_line
                self.end_line = end_line
                
                self.edit_selected_button.setEnabled(True)
                self.edit_selected_button.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                        border: 2px solid #E5E5E5;
                        border-radius: 8px;
                        padding: 20px;
                        font-size: 16px;
                        font-weight: bold;
                        text-align: left;
                        color: white;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                        border: 2px solid #E5E5E5;
                    }
                    QPushButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                        border: 2px solid #E5E5E5;
                    }
                    QPushButton:disabled {
                        background-color: #2a2a2a;
                        border: 2px solid #555;
                        color: #666;
                    }
                """)
                self.selection_status_label.setText(f"📝 Current selection ({len(self.selected_text)} characters, lines {self.start_line}-{self.end_line}) - Press F9 to cache for AI")
            else:
                self.edit_selected_button.setEnabled(False)
                self.edit_selected_button.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #333333, stop:1 #2a2a2a);
                        border: 2px solid #555555;
                        border-radius: 8px;
                        padding: 20px;
                        font-size: 16px;
                        font-weight: bold;
                        text-align: left;
                        color: #E5E5E5;
                    }
                    QPushButton:disabled {
                        background-color: #2a2a2a;
                        border: 2px solid #555555;
                        color: #E5E5E5;
                    }
                """)
                self.selection_status_label.setText("❌ No selection found - Select code and press F9 to cache it")
        except Exception as e:
            self.edit_selected_button.setEnabled(False)
            self.selection_status_label.setText(f"❌ Error checking selection: {e}")
    
    def _open_edit_code_mode(self):
        """Open the advanced edit code mode with toggle modes"""
        self.edition_mode = "edit_code"
        
        # Get current selection if any
        selected_text = ""
        start_line = 1
        end_line = 1
        
        if self.editor_widget:
            try:
                selected_text, start_line, end_line = self._get_selected_text(self.editor_widget)
            except Exception as e:
                print(f"Error getting selection: {e}")
        
        # Close this popup and open the enhanced AIEditCodeDialog
        self.close()
        
        # Open AIEditCodeDialog with toggle modes (default to full_file for edit_code mode)
        dialog = AIEditCodeDialog(
            selected_text=selected_text,
            start_line=start_line,
            end_line=end_line,
            game=self.game,
            editor_widget=self.editor_widget,  # Pass editor widget for applying changes
            toggle_mode="full_file",  # Default for edit_code mode
            parent=self.parent()
        )
        
        if dialog.exec_() == QDialog.Accepted:
            self.accept()
    
    def _open_edit_selected_mode(self):
        """Open the edit selected lines mode"""
        if not self.selected_text:
            QMessageBox.warning(self, "No Selection", "Please select some code in the editor first.")
            return
        
        self.edition_mode = "edit_selected"
        
        # Close this popup and open the edit selected dialog
        self.close()
        
        # Open edit selected dialog
        dialog = AIEditSelectedDialog(self.selected_text, self.start_line, self.end_line, self.game, self.editor_widget, self.parent())
        if dialog.exec_() == QDialog.Accepted:
            self.accept()


class AIAdvancedEditDialog(QDialog):
    """Advanced dialog for editing code with comprehensive AI assistance"""
    
    def __init__(self, editor_widget=None, game=None, parent=None):
        super().__init__(parent)
        self.editor_widget = editor_widget
        self.game = game
        self.edited_code = None
        
        self.setWindowTitle("🤖 AI Advanced Code Editor")
        self.setModal(True)
        self.setFixedSize(800, 700)
        
        # Always use global context for seamless conversation
        self.conversation_history = GAMAI_CONTEXT.get_context("global")
        GAMAI_CONTEXT.set_active_context("global")
        
        self._setup_ui()
        
        # Load current file content
        self._load_file_content()
    
    def _get_text_cursor(self, editor_widget):
        """Get text cursor from editor widget, handling both QPlainTextEdit and QsciScintilla"""
        if editor_widget is None:
            return None
            
        # Check if it's a QsciScintilla (has different methods)
        if hasattr(editor_widget, 'sendSelectionChanged'):
            # QsciScintilla doesn't have textCursor(), use its selection methods
            return editor_widget
        else:
            # QPlainTextEdit and similar widgets
            return editor_widget.textCursor()
    
    def _get_selected_text(self, editor_widget):
        """Get selected text from editor widget, handling both QPlainTextEdit and QsciScintilla"""
        if editor_widget is None:
            return "", 0, 0
            
        try:
            # Check if it's a QsciScintilla using type comparison
            if type(editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: get selection using its methods
                if editor_widget.hasSelectedText():
                    selected_text = editor_widget.selectedText()
                    # For QsciScintilla, get line numbers differently
                    line_from, index_from, line_to, index_to = editor_widget.getSelection()
                    start_line = line_from + 1
                    end_line = line_to + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
            else:
                # QPlainTextEdit and similar widgets
                cursor = editor_widget.textCursor()
                if cursor.hasSelection():
                    selected_text = cursor.selectedText()
                    start_line = cursor.blockNumber() + 1
                    end_line = cursor.blockNumber() + 1
                    if cursor.selectionEnd() != cursor.selectionStart():
                        # Multi-line selection
                        temp_cursor = QTextCursor(cursor)
                        temp_cursor.setPosition(cursor.selectionEnd())
                        end_line = temp_cursor.blockNumber() + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
        except Exception as e:
            print(f"Error getting selected text: {e}")
            return "", 0, 0

    def _setup_ui(self):
        """Setup the advanced edit dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel("🤖 AI Advanced Code Editor")
        header_label.setStyleSheet("""
            QLabel {
                color: #E5E5E5;
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 15px;
            }
        """)
        layout.addWidget(header_label)
        
        # Selection tools section
        selection_label = QLabel("🎯 Code Selection Tools:")
        selection_label.setStyleSheet("font-weight: bold; margin-bottom: 10px; color: #CCCCCC;")
        layout.addWidget(selection_label)
        
        # Selection buttons
        selection_layout = QHBoxLayout()
        
        self.select_function_button = QPushButton("📦 Select Function")
        self.select_function_button.setToolTip("Select the current function/block")
        self.select_function_button.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
                border-color: #E5E5E5;
            }
        """)
        self.select_function_button.clicked.connect(self._select_current_function)
        selection_layout.addWidget(self.select_function_button)
        
        self.select_element_button = QPushButton("🏷️ Select Element")
        self.select_element_button.setToolTip("Select the current HTML element")
        self.select_element_button.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
                border-color: #E5E5E5;
            }
        """)
        self.select_element_button.clicked.connect(self._select_current_element)
        selection_layout.addWidget(self.select_element_button)
        
        self.select_all_button = QPushButton("📄 Select All")
        self.select_all_button.setToolTip("Select entire file")
        self.select_all_button.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
                border-color: #E5E5E5;
            }
        """)
        self.select_all_button.clicked.connect(self._select_all_code)
        selection_layout.addWidget(self.select_all_button)
        
        layout.addLayout(selection_layout)
        
        # Manual selection section
        manual_label = QLabel("✏️ Manual Selection:")
        manual_label.setStyleSheet("font-weight: bold; margin: 10px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(manual_label)
        
        # Manual selection inputs
        manual_layout = QHBoxLayout()
        
        self.start_line_input = QSpinBox()
        self.start_line_input.setMinimum(1)
        self.start_line_input.setMaximum(9999)
        self.start_line_input.setValue(1)
        self.start_line_input.setPrefix("Start: ")
        self.start_line_input.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 5px;
                color: white;
                font-size: 14px;
            }
            QSpinBox:focus {
                border-color: #E5E5E5;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #3a3a3a;
                border: none;
                width: 15px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #4a4a4a;
            }
        """)
        manual_layout.addWidget(self.start_line_input)
        
        self.end_line_input = QSpinBox()
        self.end_line_input.setMinimum(1)
        self.end_line_input.setMaximum(9999)
        self.end_line_input.setValue(10)
        self.end_line_input.setPrefix("End: ")
        self.end_line_input.setStyleSheet("""
            QSpinBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 5px;
                color: white;
                font-size: 14px;
            }
            QSpinBox:focus {
                border-color: #E5E5E5;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #3a3a3a;
                border: none;
                width: 15px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #4a4a4a;
            }
        """)
        manual_layout.addWidget(self.end_line_input)
        
        self.manual_select_button = QPushButton("🎯 Select Range")
        self.manual_select_button.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 10px 15px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border-color: #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
                border-color: #E5E5E5;
            }
        """)
        self.manual_select_button.clicked.connect(self._select_line_range)
        manual_layout.addWidget(self.manual_select_button)
        
        layout.addLayout(manual_layout)
        
        # Current selection preview
        selection_preview_label = QLabel("Current Selection:")
        selection_preview_label.setStyleSheet("font-weight: bold; margin: 15px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(selection_preview_label)
        
        self.selection_preview = QTextEdit()
        self.selection_preview.setMaximumHeight(150)
        self.selection_preview.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #333;
            }
        """)
        self.selection_preview.setReadOnly(True)
        layout.addWidget(self.selection_preview)
        
        # AI instruction
        instruction_label = QLabel("🤖 AI Instructions:")
        instruction_label.setStyleSheet("font-weight: bold; margin: 15px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(instruction_label)
        
        self.instruction_input = QTextEdit()
        self.instruction_input.setPlaceholderText("Describe what you want AI to do with the selected code (e.g., 'Add a new function to handle user input', 'Change the background color to blue', 'Optimize this JavaScript code', etc.)")
        self.instruction_input.setMaximumHeight(100)
        self.instruction_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
            }
            QTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        layout.addWidget(self.instruction_input)
        
        # AI result
        result_label = QLabel("✨ AI-Edited Result:")
        result_label.setStyleSheet("font-weight: bold; margin: 10px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(result_label)
        
        self.result_text_edit = QTextEdit()
        self.result_text_edit.setMaximumHeight(200)
        self.result_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #333;
            }
        """)
        self.result_text_edit.setReadOnly(True)
        layout.addWidget(self.result_text_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.process_button = QPushButton("🤖 AI Process")
        self.process_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
                padding: 12px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.process_button.clicked.connect(self._process_with_ai)
        button_layout.addWidget(self.process_button)
        
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 12px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.accept_button = QPushButton("✅ Apply Changes")
        self.accept_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 12px 20px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """)
        self.accept_button.clicked.connect(self.accept)
        self.accept_button.setEnabled(False)
        button_layout.addWidget(self.accept_button)
        
        layout.addLayout(button_layout)
    
    def _load_file_content(self):
        """Load the full file content for AI context"""
        try:
            if self.game and self.game.html_path and self.game.html_path.exists():
                with open(self.game.html_path, 'r', encoding='utf-8') as f:
                    self.full_file_content = f.read()
            else:
                self.full_file_content = ""
        except Exception as e:
            print(f"Error loading file content: {e}")
            self.full_file_content = ""
    
    def _load_current_context(self):
        """Load current game manifest and file content for updated AI context"""
        try:
            # Load manifest if available
            if hasattr(self, 'game') and self.game and hasattr(self.game, 'game_file') and self.game.game_file:
                manifest_path = Path(self.game.game_file).with_name('manifest.json')
                if manifest_path.exists():
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        self.manifest_content = f.read()
                else:
                    self.manifest_content = ""
            else:
                self.manifest_content = ""
            
            # Reload current file content to get latest changes
            self._load_file_content()
            
            print("✅ Loaded current context for AI: manifest + current file content")
            
        except Exception as e:
            print(f"Error loading current context: {e}")
            self.manifest_content = ""
            # Try to at least load the file content
            try:
                self._load_file_content()
            except:
                self.full_file_content = ""
    
    def _select_current_function(self):
        """Select the current function/block"""
        # TODO: Implement function selection logic
        QMessageBox.information(self, "Feature", "Function selection will be implemented in the next update.")
    
    def _select_current_element(self):
        """Select the current HTML element"""
        # TODO: Implement element selection logic
        QMessageBox.information(self, "Feature", "Element selection will be implemented in the next update.")
    
    def _select_all_code(self):
        """Select entire file"""
        if self.editor_widget:
            # Check if it's a QsciScintilla using type comparison
            if type(self.editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: select entire document
                self.editor_widget.selectAll()
                selected_text = self.editor_widget.text()
                # Update preview
                self.selection_preview.setPlainText(selected_text)
            else:
                # QPlainTextEdit and similar widgets
                cursor = self.editor_widget.textCursor()
                cursor.select(QTextCursor.Document)
                self.editor_widget.setTextCursor(cursor)
                
                # Update preview
                self.selection_preview.setPlainText(cursor.selectedText())
    
    def _select_line_range(self):
        """Select a specific line range"""
        start_line = self.start_line_input.value()
        end_line = self.end_line_input.value()
        
        if start_line > end_line:
            QMessageBox.warning(self, "Invalid Range", "Start line must be less than or equal to end line.")
            return
        
        if self.editor_widget:
            # Check if it's a QsciScintilla using type comparison
            if type(self.editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: set selection using line/column positions
                # QsciScintilla lines are 0-indexed
                line_from = start_line - 1
                index_from = 0
                line_to = end_line - 1
                index_to = 999999  # Large number to get to end of line
                
                self.editor_widget.setSelection(line_from, index_from, line_to, index_to)
                
                # Update preview
                selected_text = self.editor_widget.selectedText()
                self.selection_preview.setPlainText(selected_text)
            else:
                # QPlainTextEdit and similar widgets
                cursor = self.editor_widget.textCursor()
                
                # Move to start of start line
                cursor.movePosition(QTextCursor.Start)
                for i in range(start_line - 1):
                    cursor.movePosition(QTextCursor.Down)
                
                # Select to end of end line
                for i in range(end_line - start_line + 1):
                    cursor.movePosition(QTextCursor.EndOfLine)
                    if i < end_line - start_line:
                        cursor.movePosition(QTextCursor.Down)
                
                self.editor_widget.setTextCursor(cursor)
                
                # Update preview
                self.selection_preview.setPlainText(cursor.selectedText())
    
    def _process_with_ai(self):
        """Process the code editing request with AI"""
        if not self.editor_widget:
            QMessageBox.warning(self, "No Editor", "No editor widget available.")
            return
        
        instruction = self.instruction_input.toPlainText().strip()
        if not instruction:
            QMessageBox.warning(self, "No Instruction", "Please describe what you want AI to do with the code.")
            return
        
        try:
            # Disable process button during processing
            self.process_button.setEnabled(False)
            self.process_button.setText("🤖 Processing...")
            
            # Load current context BEFORE AI processing (user's suggestion)
            self._load_current_context()
            
            # Get current selection
            if type(self.editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla
                if not self.editor_widget.hasSelectedText():
                    QMessageBox.warning(self, "No Selection", "Please select some code first.")
                    return
                selected_code = self.editor_widget.selectedText()
            else:
                # QPlainTextEdit and similar
                cursor = self.editor_widget.textCursor()
                if not cursor.hasSelection():
                    QMessageBox.warning(self, "No Selection", "Please select some code first.")
                    return
                selected_code = cursor.selectedText()
            
            # Create AI prompt for advanced code editing
            prompt = self._create_ai_prompt(instruction, selected_code)
            
            # Call AI to edit the code
            self._call_ai_for_code_edit(prompt)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process with AI: {e}")
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
    
    def _create_ai_prompt(self, instruction, selected_code):
        """Create the AI prompt for advanced code editing"""
        prompt = f"""You are an expert HTML/CSS/JavaScript developer. I need you to edit specific selected code based on user instructions.

USER INSTRUCTION: {instruction}

SELECTED CODE TO EDIT:
```html
{selected_code}
```

FULL FILE CONTEXT:
```html
{self.full_file_content}
```

MANIFEST CONTEXT (if available):
```json
{getattr(self, 'manifest_content', 'No manifest available')}
```

TASK:
1. Analyze the selected code in the context of the full file
2. Apply the user's instructions to modify/improve the selected code
3. ⚠️ CRITICAL: Return the COMPLETE selected code with your modifications integrated
4. ⚠️ DO NOT return only the changed parts - return the ENTIRE selected code block
5. ⚠️ If your instruction only affects part of the code, keep ALL other parts unchanged
6. Ensure the edited code maintains proper syntax and formatting
7. Keep the code functional and integrate well with the surrounding code
8. If the instruction requires context outside the selected code, intelligently infer or create appropriate code

MODE DETECTION:
- If the instruction requires modifying code OUTSIDE the selected area, suggest using 'Edit Code' mode instead
- If the instruction is too broad for the selected code, suggest using 'Edit Code' mode
- Examples that need Edit Code mode: "add a new function", "change the page layout", "add new sections"

CRITICAL SPACING PRESERVATION INSTRUCTION:
- For HTML content: ALWAYS prefix the FIRST line of your response with "<!--.-->"
- For CSS content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- For JavaScript content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- This invisible comment is essential for preserving leading spaces during copy/paste
- Example: If your HTML response starts with "    <div class='test'>", write "<!--.-->     <div class='test'>"
- The comment will be invisible but ensures all leading spaces are preserved

RESPONSE FORMAT:
- Return ONLY the complete edited selected code
- Do not include explanations, line numbers, or additional text
- Do not include "Here is the modified code:" or similar prefixes"""
        return prompt
    
    def _call_ai_for_code_edit(self, prompt):
        """Call AI to edit the selected code"""
        try:
            # Create AI model instance
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                raise Exception("AI model not available")
            
            # Show current model being used
            self.process_button.setText(f"🤖 AI Processing ({model_name})...")
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                ai_response = response.text.strip()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name}, switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        raise Exception("Failed to switch to backup model")
                    
                    # Update button text to show backup model
                    self.process_button.setText(f"🤖 AI Processing ({backup_model_name})...")
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    ai_response = response.text.strip()
                else:
                    # Re-raise if it's not a rate limit error
                    raise rate_limit_error
            
            # Extract content from markdown code blocks if present
            extracted_content = extract_content_from_code_blocks(ai_response)
            
            # Set the result
            self.result_text_edit.setPlainText(ai_response)
            self.edited_code = extracted_content
            
            # Enable accept button
            self.accept_button.setEnabled(True)
            
            # Re-enable process button
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
            
            QMessageBox.information(self, "Success", "AI has processed your code. Review the result and click 'Apply Changes' to use it.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"AI processing failed: {e}")
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
    
    def get_edited_code(self):
        """Get the AI-edited code"""
        return self.edited_code
    
    def accept(self):
        """Apply the edited code back to the editor when dialog is accepted"""
        try:
            if self.edited_code and self.editor_widget:
                # Replace the entire content in the editor
                if hasattr(self.editor_widget, 'setPlainText'):
                    # QPlainTextEdit
                    self.editor_widget.setPlainText(self.edited_code)
                elif hasattr(self.editor_widget, 'setText'):
                    # QTextEdit
                    self.editor_widget.setText(self.edited_code)
                else:
                    # For other widget types, try to set content
                    if hasattr(self.editor_widget, 'textCursor'):
                        cursor = self.editor_widget.textCursor()
                        cursor.select(QTextCursor.Document)
                        cursor.insertText(self.edited_code)
                        self.editor_widget.setTextCursor(cursor)
            
            # Call parent accept to close the dialog
            super().accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply edited code: {e}")


class AIEditSelectedDialog(QDialog):
    """Enhanced dialog for editing selected lines with smart prompt analysis"""
    
    def __init__(self, selected_text, start_line, end_line, game, editor_widget=None, parent=None):
        super().__init__(parent)
        self.selected_text = selected_text
        self.start_line = start_line
        self.end_line = end_line
        self.game = game
        self.editor_widget = editor_widget
        self.edited_code = None
        self.prompt_analysis_result = None
        
        self.setWindowTitle(f"🤖 AI Edit Selected - Lines {start_line}-{end_line}")
        self.setModal(True)
        self.setFixedSize(700, 600)
        
        # Always use global context for seamless conversation
        self.conversation_history = GAMAI_CONTEXT.get_context("global")
        GAMAI_CONTEXT.set_active_context("global")
        
        self._setup_ui()
        
        # Load current file content for AI context
        self._load_file_content()
    
    def _setup_ui(self):
        """Setup the enhanced AI edit selected dialog UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Header
        header_label = QLabel("🤖 AI Edit Selected")
        header_label.setStyleSheet("""
            QLabel {
                color: #E5E5E5;
                font-size: 20px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(header_label)
        
        # Selection info
        selection_info = QLabel(f"Selected Code (Lines {self.start_line}-{self.end_line}):")
        selection_info.setStyleSheet("font-weight: bold; margin-bottom: 5px; color: #CCCCCC;")
        layout.addWidget(selection_info)
        
        # Selected code preview
        self.selected_text_edit = QTextEdit()
        self.selected_text_edit.setPlainText(self.selected_text)
        self.selected_text_edit.setMaximumHeight(120)
        self.selected_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #333;
            }
        """)
        self.selected_text_edit.setReadOnly(True)
        layout.addWidget(self.selected_text_edit)
        
        # AI instruction
        instruction_label = QLabel("🤖 What would you like AI to do?")
        instruction_label.setStyleSheet("font-weight: bold; margin: 15px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(instruction_label)
        
        self.instruction_input = QTextEdit()
        self.instruction_input.setPlaceholderText("Describe what you want AI to change, add, or improve in the selected code...")
        self.instruction_input.setMaximumHeight(100)
        self.instruction_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
                color: white;
            }
            QTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        layout.addWidget(self.instruction_input)
        
        # Prompt relevance check
        self.relevance_label = QLabel()
        self.relevance_label.setStyleSheet("color: #666; font-size: 12px; margin-top: 5px;")
        layout.addWidget(self.relevance_label)
        
        # AI result preview
        result_label = QLabel("✨ AI-Edited Result:")
        result_label.setStyleSheet("font-weight: bold; margin: 10px 0 5px 0; color: #CCCCCC;")
        layout.addWidget(result_label)
        
        self.result_text_edit = QTextEdit()
        self.result_text_edit.setMaximumHeight(180)
        self.result_text_edit.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px;
                font-family: 'Courier New', monospace;
                font-size: 12px;
                color: #333;
            }
        """)
        self.result_text_edit.setReadOnly(True)
        layout.addWidget(self.result_text_edit)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.process_button = QPushButton("🤖 AI Process")
        self.process_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
                padding: 12px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.process_button.clicked.connect(self._process_with_ai)
        button_layout.addWidget(self.process_button)
        
        button_layout.addStretch()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 12px 20px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.accept_button = QPushButton("✅ Apply Changes")
        self.accept_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 12px 20px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #ccc;
                color: #666;
            }
        """)
        self.accept_button.clicked.connect(self.accept)
        self.accept_button.setEnabled(False)
        button_layout.addWidget(self.accept_button)
        
        layout.addLayout(button_layout)
    
    def _load_current_context(self):
        """Load current context for AI processing"""
        try:
            # Load enhanced AI context using the global function
            if self.game:
                self.enhanced_context = _load_enhanced_ai_context(
                    self.game, 
                    self.selected_text, 
                    self.start_line, 
                    self.end_line
                )
            else:
                self.enhanced_context = {}
        except Exception as e:
            print(f"Error loading current context: {e}")
            self.enhanced_context = {}
    
    def _load_file_content(self):
        """Load the full file content for AI context"""
        try:
            if self.game and self.game.html_path and self.game.html_path.exists():
                with open(self.game.html_path, 'r', encoding='utf-8') as f:
                    self.full_file_content = f.read()
            else:
                self.full_file_content = ""
        except Exception as e:
            print(f"Error loading file content: {e}")
            self.full_file_content = ""
    
    def _process_with_ai(self):
        """Process the code editing request with AI and prompt analysis"""
        instruction = self.instruction_input.toPlainText().strip()
        if not instruction:
            QMessageBox.warning(self, "No Instruction", "Please describe what you want AI to do with the selected code.")
            return
        
        try:
            # Disable process button during processing
            self.process_button.setEnabled(False)
            self.process_button.setText("🤖 Processing...")
            
            # Load current context BEFORE AI processing (user's suggestion)
            self._load_current_context()
            
            # First, check prompt relevance
            relevance_check = self._check_prompt_relevance(instruction)
            
            if relevance_check == "unrelated":
                # Show fallback dialog
                self._show_incompatibility_dialog(instruction)
                return
            
            # Create AI prompt for code editing
            prompt = self._create_ai_prompt(instruction)
            
            # Call AI to edit the code
            self._call_ai_for_code_edit(prompt)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process with AI: {e}")
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
    
    def _check_prompt_relevance(self, instruction):
        """Check if the user instruction is relevant to the selected code"""
        try:
            prompt = f"""Analyze if the user's instruction is relevant to the selected code.

SELECTED CODE:
```html
{self.selected_text}
```

USER INSTRUCTION: {instruction}

TASK: Determine if the instruction can be meaningfully applied to the selected code. Consider:
1. Does the instruction relate to the content of the selected code?
2. Can the instruction be fulfilled by modifying just the selected code?
3. Would the instruction make sense in this context?

Respond with only one word:
- "relevant" if the instruction can be meaningfully applied to the selected code
- "unrelated" if the instruction doesn't match the selected content

Example of unrelated: Selecting a div element but asking to "change the button color" when there's no button in the selected code."""

            # Create AI model instance
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                return "relevant"  # Default to allowing if AI is not available
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                result = response.text.strip().lower()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name} (prompt check), switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        return "relevant"  # Default to allowing if backup fails
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    result = response.text.strip().lower()
                else:
                    # Re-raise if it's not a rate limit error
                    raise rate_limit_error
            
            self.prompt_analysis_result = result
            if result == "unrelated":
                self.relevance_label.setText("⚠️ Warning: Your instruction may not match the selected code. AI will offer alternatives.")
                self.relevance_label.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px;")
            else:
                self.relevance_label.setText("✅ Your instruction looks relevant to the selected code.")
                self.relevance_label.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px;")
            
            return result
            
        except Exception as e:
            print(f"Error checking prompt relevance: {e}")
            return "relevant"  # Default to allowing if check fails
    
    def _show_incompatibility_dialog(self, instruction):
        """Show dialog when prompt doesn't match selected content"""
        reply = QMessageBox.question(
            self,
            "Instruction Mismatch",
            f"Your instruction doesn't seem to match the selected code:\n\n"
            f"Instruction: {instruction}\n"
            f"Selected: {self.selected_text[:100]}{'...' if len(self.selected_text) > 100 else ''}\n\n"
            f"Would you like to use the advanced 'Edit Code' mode instead?\n"
            f"This mode allows more comprehensive code modifications.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.close()
            # Open advanced edit dialog
            dialog = AIAdvancedEditDialog(None, self.game, self.parent())
            if dialog.exec_() == QDialog.Accepted:
                self.accept()
        else:
            # Allow user to continue anyway
            self.relevance_label.setText("⚠️ Proceeding anyway. AI will do its best to help.")
            self.relevance_label.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px;")
            
            # Continue with normal processing
            prompt = self._create_ai_prompt(instruction)
            self._call_ai_for_code_edit(prompt)
    
    def _create_ai_prompt(self, instruction):
        """Create the AI prompt for code editing"""
        prompt = f"""You are an expert HTML/CSS/JavaScript developer. I need you to edit specific selected code based on user instructions.

USER INSTRUCTION: {instruction}

SELECTED CODE TO EDIT:
```html
{self.selected_text}
```

FULL FILE CONTEXT:
```html
{self.full_file_content}
```

MANIFEST CONTEXT (if available):
```json
{getattr(self, 'manifest_content', 'No manifest available')}
```

TASK:
1. Analyze the selected code in the context of the full file
2. Apply the user's instructions to modify/improve the selected code
3. ⚠️ CRITICAL: Return the COMPLETE selected code with your modifications integrated
4. ⚠️ DO NOT return only the changed parts - return the ENTIRE selected code block
5. ⚠️ If your instruction only affects part of the code, keep ALL other parts unchanged
6. Ensure the edited code maintains proper syntax and formatting
7. Keep the code functional and integrate well with the surrounding code

MODE DETECTION:
- If the instruction requires modifying code OUTSIDE the selected area, suggest using 'Edit Code' mode instead
- If the instruction is too broad for the selected code, suggest using 'Edit Code' mode
- Examples that need Edit Code mode: "add a new function", "change the page layout", "add new sections"

CRITICAL SPACING PRESERVATION INSTRUCTION:
- For HTML content: ALWAYS prefix the FIRST line of your response with "<!--.-->"
- For CSS content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- For JavaScript content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- This invisible comment is essential for preserving leading spaces during copy/paste
- Example: If your HTML response starts with "    <div class='test'>", write "<!--.-->     <div class='test'>"
- The comment will be invisible but ensures all leading spaces are preserved

RESPONSE FORMAT:
- Return ONLY the complete edited selected code
- Do not include explanations, line numbers, or additional text
- Do not include "Here is the modified code:" or similar prefixes"""
        return prompt
    
    def _call_ai_for_code_edit(self, prompt):
        """Call AI to edit the selected code"""
        try:
            # Create AI model instance
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                raise Exception("AI model not available")
            
            # Show current model being used
            self.process_button.setText(f"🤖 AI Processing ({model_name})...")
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                ai_response = response.text.strip()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name}, switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        raise Exception("Failed to switch to backup model")
                    
                    # Update button text to show backup model
                    self.process_button.setText(f"🤖 AI Processing ({backup_model_name})...")
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    ai_response = response.text.strip()
                else:
                    # Re-raise if it's not a rate limit error
                    raise rate_limit_error
            
            # Extract content from markdown code blocks if present
            extracted_content = extract_content_from_code_blocks(ai_response)
            
            # Set the result
            self.result_text_edit.setPlainText(ai_response)
            self.edited_code = extracted_content
            
            # Enable accept button
            self.accept_button.setEnabled(True)
            
            # Re-enable process button
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
            
            QMessageBox.information(self, "Success", "AI has processed your code. Review the result and click 'Apply Changes' to use it.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"AI processing failed: {e}")
            self.process_button.setEnabled(True)
            self.process_button.setText("🤖 AI Process")
    
    def get_edited_code(self):
        """Get the AI-edited code"""
        return self.edited_code
    
    def accept(self):
        """Apply the edited code back to the editor by replacing the originally selected text"""
        try:
            if not self.edited_code:
                QMessageBox.warning(self, "No Code", "No edited code to apply.")
                return
            
            if not self.editor_widget:
                QMessageBox.warning(self, "No Editor", "No editor widget available.")
                return
            
            print(f"🔧 Applying AI edited code - Original selection: '{self.selected_text[:50]}...' ({len(self.selected_text)} chars)")
            print(f"🔧 New edited code: '{self.edited_code[:50]}...' ({len(self.edited_code)} chars)")
            
            # Add HTML comment to the first line of edited code for spacing preservation
            print(f"🔧 Original edited code: {repr(self.edited_code[:50])}{'...' if len(self.edited_code) > 50 else ''}")
            
            # Handle different editor types
            if type(self.editor_widget).__name__ == 'QsciScintilla':
                # Handle QsciScintilla editor
                if self.editor_widget.hasSelectedText():
                    # Get the current selection
                    line_from, index_from, line_to, index_to = self.editor_widget.getSelection()
                    
                    # Replace the selected text using original method (now with HTML comment preservation!)
                    self.editor_widget.replaceSelectedText(self.edited_code)
                    print("✅ Replaced selection in QsciScintilla editor (AI comment method)")
                else:
                    # If no current selection, try to find and replace the original selected text
                    full_text = self.editor_widget.text()
                    selected_start = full_text.find(self.selected_text)
                    if selected_start != -1:
                        # Select the original text and replace it using original method
                        self.editor_widget.setSelection(selected_start, selected_start + len(self.selected_text))
                        # Use original method (now with AI comment preservation!)
                        self.editor_widget.replaceSelectedText(self.edited_code)
                        print("✅ Found and replaced original selection in QsciScintilla editor (AI comment method)")
                    else:
                        QMessageBox.warning(self, "Selection Not Found", "Could not find the originally selected text in the editor.")
                        return
            
            elif hasattr(self.editor_widget, 'textCursor'):
                # Handle QPlainTextEdit and similar editors
                cursor = self.editor_widget.textCursor()
                full_text = self.editor_widget.toPlainText()
                
                # Try to find the original selected text in the current content
                selected_start = full_text.find(self.selected_text)
                
                if selected_start != -1:
                    # Create a cursor at the start of the found text
                    new_cursor = QTextCursor(self.editor_widget.document())
                    new_cursor.setPosition(selected_start)
                    
                    # Select the original text
                    new_cursor.setPosition(selected_start + len(self.selected_text), QTextCursor.KeepAnchor)
                    
                    # Replace the selected text using original method (now with HTML comment preservation!)
                    self.editor_widget.setTextCursor(new_cursor)
                    # Use original cursor method (now with HTML comment preservation!)
                    cursor.insertText(self.edited_code)
                    print("✅ Found and replaced original selection in text editor (AI comment method)")
                elif cursor.hasSelection():
                    # If we can't find the original text, but there's a current selection, replace that
                    # Use original method (now with AI comment preservation!)
                    cursor.insertText(self.edited_code)
                    print("✅ Replaced current selection in text editor (AI comment method)")
                else:
                    QMessageBox.warning(self, "Selection Not Found", "Could not find the originally selected text in the editor.")
                    return
            
            elif hasattr(self.editor_widget, 'setPlainText'):
                # Fallback for basic text editors - replace entire content
                self.editor_widget.setPlainText(self.edited_code)
                print("✅ Replaced entire content in basic text editor")
            else:
                QMessageBox.warning(self, "Unsupported Editor", "Editor type not supported for text replacement.")
                return
            
            # Log AI edit activity
            self._log_ai_edit_activity()
            
            # Call parent accept to close the dialog
            super().accept()
            print("✅ AI edit applied successfully!")
            
        except Exception as e:
            print(f"❌ Error applying edited code: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to apply edited code: {e}")
            
    def _log_ai_edit_activity(self):
        """Log AI edit activity for enhanced context awareness"""
        try:
            log_entry = f"user edited game '{self.game.name}' using edit_selected mode (lines {self.start_line}-{self.end_line})"
            
            # Add to global GAMAI context for AI awareness
            GAMAI_CONTEXT.add_message("global", "system", f"📝 Activity Log: {log_entry}")
            
            # Print to console
            print(f"📝 Activity Log: {log_entry}")
            
            # Also add via parent method if available
            if hasattr(self.parent(), 'add_activity_log'):
                self.parent().add_activity_log(log_entry)
                
        except Exception as e:
            print(f"Error logging AI edit activity: {e}")


class GameCreationDialog(QDialog):
    """Dialog for creating a new game"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Game")
        self.setFixedSize(700, 890)  # Increased height by 150px for better category scrolling
        self.setModal(True)
        self.game_data = None
        self._setup_ui()
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=250)
    
    def closeEvent(self, event):
        """Close dialog with fade-out animation"""
        fade_widget_out(self, duration=200, hide_after=False)
        event.accept()
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=200, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=200, hide_after=True)
        super().reject()
    
    def _setup_ui(self):
        # Main layout with scroll area for unlimited content
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)  # No spacing for clean scroll area
        main_layout.setContentsMargins(0, 0, 0, 0)  # No margins for full scroll width
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Only vertical scroll
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1a1a1a;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #E5E5E5;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #E5E5E5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Content widget for scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(15)  # Optimized from 20px for better space efficiency  # Optimized from 25px for better space efficiency
        layout.setContentsMargins(25, 20, 25, 20)  # Optimized margins from 30x25x30x25
        
        # Title
        title_label = QLabel("Create New Game")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: white; margin: 15px;")
        layout.addWidget(title_label)
        
        # Game name input
        name_layout = QVBoxLayout()
        name_label = QLabel("Game Name:")
        name_label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 8px;")
        self.name_input = QLineEdit("game1")
        self.name_input.setPlaceholderText("Enter your game name...")
        self.name_input.setMinimumHeight(75)  # Optimized from 80px for better space efficiency
        self.name_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Better responsive behavior
        self.name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized from 30px for better space efficiency */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        self.name_input.textChanged.connect(self._validate_inputs)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # Extra spacer between name and version for better separation
        spacer_label = QLabel()  # Invisible spacer
        spacer_label.setFixedHeight(10)  # Small spacer height
        spacer_label.setStyleSheet("background-color: transparent;")  # Invisible
        layout.addWidget(spacer_label)
        
        # Version input
        version_layout = QVBoxLayout()
        version_label = QLabel("Version:")
        version_label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 8px;")
        self.version_input = QLineEdit("0.0.1")
        self.version_input.setPlaceholderText("Enter version (e.g., 0.0.1)")
        self.version_input.setMinimumHeight(75)  # Optimized from 80px for better space efficiency
        self.version_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Better responsive behavior
        self.version_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized from 30px for better space efficiency */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        self.version_input.textChanged.connect(self._validate_inputs)
        version_layout.addWidget(version_label)
        version_layout.addWidget(self.version_input)
        layout.addLayout(version_layout)
        
        # Game metadata (Type and Players)
        metadata_layout = QGridLayout()
        
        # Type field (2D/3D)
        type_label = QLabel("Type:")
        type_label.setStyleSheet("color: white; font-size: 16px;")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["2D", "3D"])
        self.type_combo.setCurrentText("2D")  # Default to 2D
        self.type_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized to 28px for better text space - matches name/version inputs */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
        """)
        
        # Players field (1 or 2)
        players_label = QLabel("Players:")
        players_label.setStyleSheet("color: white; font-size: 16px;")
        self.players_combo = QComboBox()
        self.players_combo.addItems(["1", "2"])
        self.players_combo.setCurrentText("1")  # Default to 1 player
        self.players_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized to 28px for better text space - matches name/version inputs */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
        """)
        
        # Add to grid layout
        metadata_layout.addWidget(type_label, 0, 0)
        metadata_layout.addWidget(self.type_combo, 0, 1)
        metadata_layout.addWidget(players_label, 1, 0)
        metadata_layout.addWidget(self.players_combo, 1, 1)
        metadata_layout.setSpacing(15)
        
        layout.addLayout(metadata_layout)
        
        # Categories section
        categories_layout = QVBoxLayout()
        categories_layout.setSpacing(20)
        
        # Main Categories (max 5 selections)
        main_cat_layout = QVBoxLayout()
        main_cat_label = QLabel("Main-Category (Max 5):")
        main_cat_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; margin-bottom: 15px; margin-top: 10px;")
        main_cat_label.setWordWrap(True)  # Enable text wrapping for longer labels
        
        # Create scrollable main categories list using search dialog pattern
        self.main_categories_scroll = QScrollArea()
        self.main_categories_scroll.setMaximumHeight(400)  # Increased significantly for unlimited vertical space
        self.main_categories_scroll.setWidgetResizable(True)
        self.main_categories_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        # Create widget to hold the checkboxes
        self.main_categories_widget = QWidget()
        self.main_categories_list_layout = QVBoxLayout(self.main_categories_widget)
        
        # Create checkboxes for each category
        self.main_category_checkboxes = {}
        for category in MAIN_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_main_category_changed)
            self.main_categories_list_layout.addWidget(checkbox)
            self.main_category_checkboxes[category] = checkbox
        
        # Add stretch to keep items at top
        self.main_categories_list_layout.addStretch()
        self.main_categories_scroll.setWidget(self.main_categories_widget)
        
        # Create count label for main categories
        self.main_cat_count_label = QLabel("Selected: 0/5")
        self.main_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        
        # Setup group box layout
        main_cat_group = QGroupBox("🏷️ Main Categories")
        main_cat_layout = QVBoxLayout(main_cat_group)
        main_cat_layout.addWidget(self.main_categories_scroll)
        main_cat_layout.addWidget(self.main_cat_count_label)
        main_cat_group.setLayout(main_cat_layout)
        

        # Sub Categories (unlimited selections)
        sub_cat_layout = QVBoxLayout()
        sub_cat_label = QLabel("Sub-Category (Unlimited):")
        sub_cat_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; margin-bottom: 15px; margin-top: 15px;")
        sub_cat_label.setWordWrap(True)  # Enable text wrapping for longer labels
        
        # Create scrollable sub categories list using search dialog pattern
        self.sub_categories_scroll = QScrollArea()
        self.sub_categories_scroll.setMaximumHeight(500)  # Increased significantly for unlimited vertical space
        self.sub_categories_scroll.setWidgetResizable(True)
        self.sub_categories_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        # Create widget to hold the checkboxes
        self.sub_categories_widget = QWidget()
        self.sub_categories_list_layout = QVBoxLayout(self.sub_categories_widget)
        
        # Create checkboxes for each category
        self.sub_category_checkboxes = {}
        for category in SUB_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_sub_category_changed)
            self.sub_categories_list_layout.addWidget(checkbox)
            self.sub_category_checkboxes[category] = checkbox
        
        # Add stretch to keep items at top
        self.sub_categories_list_layout.addStretch()
        self.sub_categories_scroll.setWidget(self.sub_categories_widget)
        
        # Create count label for sub categories
        self.sub_cat_count_label = QLabel("Selected: 0")
        self.sub_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        
        # Setup group box layout
        sub_cat_group = QGroupBox("🏷️ Sub Categories")
        sub_cat_layout = QVBoxLayout(sub_cat_group)
        sub_cat_layout.addWidget(self.sub_categories_scroll)
        sub_cat_layout.addWidget(self.sub_cat_count_label)
        sub_cat_group.setLayout(sub_cat_layout)
        
        # Connect signals to update count labels and enforce limits
        # Checkbox connections are set up during checkbox creation
        
        # Add to categories layout
        categories_layout.addWidget(main_cat_group)
        categories_layout.addWidget(sub_cat_group)
        
        layout.addLayout(categories_layout)
        
        # Spacer
        layout.addStretch()
        
        # Button section with extra padding to prevent collision
        button_section = QVBoxLayout()
        button_section.setSpacing(20)  # Increased from 10px to 20px space before buttons
        button_section.addStretch()  # Push buttons to bottom
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(35)  # Optimized from 40px for better space efficiency
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedSize(140, 45)  # Increased from 120x40 for better usability
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.next_button = QPushButton("Next →")
        self.next_button.setFixedSize(160, 45)  # Increased from 120x40 for better usability
        self.next_button.setCursor(Qt.PointingHandCursor)
        self.next_button.setEnabled(False)  # Initially disabled
        self.next_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
            }
        """)
        self.next_button.clicked.connect(self._create_game)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        button_layout.addWidget(self.next_button)
        
        button_section.addLayout(button_layout)
        layout.addLayout(button_section)
        
        # Setup scroll area
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # Set dialog background
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
            QCheckBox {
                color: white;
                font-size: 13px;
            }
        """)  # Search dialog pattern styling
        
        # Set focus to name input
        self.name_input.setFocus()
    
    def _on_main_category_changed(self, state):
        """Handle main category selection changes and enforce 5-selection limit"""
        # Enforce 5-selection limit
        checked_count = sum(1 for checkbox in self.main_category_checkboxes.values() if checkbox.isChecked())
        
        if checked_count > 5:
            # Find and uncheck the checkbox that was just checked
            checkbox = self.sender()
            if checkbox:
                checkbox.setChecked(False)
                checked_count -= 1
            QMessageBox.information(self, "Selection Limit", "You can select a maximum of 5 main categories.")
        
        # Update count label
        self.main_cat_count_label.setText(f"Selected: {checked_count}/5")
        
        # Change color if limit reached
        if checked_count >= 5:
            self.main_cat_count_label.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px; font-weight: bold;")
        else:
            self.main_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
    
    def _on_sub_category_changed(self, state):
        """Handle sub category selection changes"""
        checked_count = sum(1 for checkbox in self.sub_category_checkboxes.values() if checkbox.isChecked())
        
        # Update count label
        self.sub_cat_count_label.setText(f"Selected: {checked_count}")
    
    def _validate_inputs(self):
        """Enable/disable Next button based on input validity"""
        name_text = self.name_input.text().strip()
        if name_text and len(name_text) >= 1:
            self.next_button.setEnabled(True)
        else:
            self.next_button.setEnabled(False)
    
    def _create_game(self):
        name = self.name_input.text().strip()
        version = self.version_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Invalid Input", "Please enter a game name.")
            return
        
        if not version:
            version = "0.0.1"
        
        # Get selected categories from checkboxes
        selected_main_categories = []
        for category, checkbox in self.main_category_checkboxes.items():
            if checkbox.isChecked():
                selected_main_categories.append(category)
        
        selected_sub_categories = []
        for category, checkbox in self.sub_category_checkboxes.items():
            if checkbox.isChecked():
                selected_sub_categories.append(category)
        
        self.game_data = {
            "name": name, 
            "version": version, 
            "type": self.type_combo.currentText(), 
            "players": self.players_combo.currentText(),
            "main_categories": selected_main_categories,
            "sub_categories": selected_sub_categories
        }
        self.accept()


class AICreationOptionsDialog(QDialog):
    """Dialog for choosing between Surprise and One-Shot creation options"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Game Creation Options")
        self.setFixedSize(500, 340)
        self.setModal(True)
        self.selected_type = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("Choose AI Game Creation Method:")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 20px; color: #CCCCCC;")
        layout.addWidget(title_label)
        
        # Surprise Button
        self.surprise_button = QPushButton("🎲 Surprise")
        self.surprise_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
                color: white;
                margin: 10px;
                padding: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.surprise_button.clicked.connect(self._select_surprise)
        layout.addWidget(self.surprise_button)
        
        # One-Shot Button  
        self.oneshot_button = QPushButton("⚡ One-Shot")
        self.oneshot_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
                color: white;
                margin: 10px;
                padding: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.oneshot_button.clicked.connect(self._select_oneshot)
        layout.addWidget(self.oneshot_button)
        
        # For You Button
        self.foryou_button = QPushButton("🎯 For You")
        self.foryou_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 10px;
                font-size: 16px;
                font-weight: bold;
                color: white;
                margin: 10px;
                padding: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.foryou_button.clicked.connect(self._select_foryou)
        layout.addWidget(self.foryou_button)
        
        # Description
        description_label = QLabel("Surprise: AI creates a mystery game\nOne-Shot: Customize and generate a complete game\nFor You: Generate games based on your collection")
        description_label.setAlignment(Qt.AlignCenter)
        description_label.setStyleSheet("font-size: 12px; color: #666; margin-top: 10px;")
        layout.addWidget(description_label)
    
    def _select_surprise(self):
        self.selected_type = "surprise"
        self.accept()
    
    def _select_oneshot(self):
        self.selected_type = "oneshot"
        self.accept()
    
    def _select_foryou(self):
        self.selected_type = "foryou"
        self.accept()
    
    def get_selected_type(self):
        return self.selected_type
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=200)
    
    def closeEvent(self, event):
        """Close dialog with fade-out animation"""
        fade_widget_out(self, duration=150, hide_after=False)
        event.accept()
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=150, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=150, hide_after=True)
        super().reject()


class GameImportDialog(QDialog):
    """Dialog for importing a game from external HTML file"""
    
    def __init__(self, parent=None, suggested_name=""):
        super().__init__(parent)
        self.setWindowTitle("Import Game")
        self.setFixedSize(800, 800)  # Fixed size for scrollable content area (same as manifest)
        self.setModal(True)
        self.game_data = None
        self._setup_ui(suggested_name)
    
    def _setup_ui(self, suggested_name):
        # Main layout with scroll area for unlimited content
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)  # No spacing for clean scroll area
        main_layout.setContentsMargins(0, 0, 0, 0)  # No margins for full scroll width
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Only vertical scroll
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1a1a1a;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #E5E5E5;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #E5E5E5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Content widget for scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 20, 25, 20)
        
        # Title
        title_label = QLabel("Import Game")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: white; margin: 15px;")
        layout.addWidget(title_label)
        
        # Info label
        info_label = QLabel("Set the game details below:")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("font-size: 14px; color: #E5E5E5; margin-bottom: 20px;")
        layout.addWidget(info_label)
        
        # Game name input
        name_layout = QVBoxLayout()
        name_label = QLabel("Game Name:")
        name_label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 8px;")
        self.name_input = QLineEdit(suggested_name if suggested_name else "Imported Game")
        self.name_input.setPlaceholderText("Enter your game name...")
        self.name_input.setMinimumHeight(75)  # Optimized from 80px for better space efficiency
        self.name_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Better responsive behavior
        self.name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized from 30px for better space efficiency */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        self.name_input.textChanged.connect(self._validate_inputs)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        layout.addLayout(name_layout)
        
        # Extra spacer between name and version for better separation
        spacer_label = QLabel()  # Invisible spacer
        spacer_label.setFixedHeight(10)  # Small spacer height
        spacer_label.setStyleSheet("background-color: transparent;")  # Invisible
        layout.addWidget(spacer_label)
        
        # Version input
        version_layout = QVBoxLayout()
        version_label = QLabel("Version:")
        version_label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 8px;")
        self.version_input = QLineEdit("1.0.0")
        self.version_input.setPlaceholderText("Enter version (e.g., 1.0.0)")
        self.version_input.setMinimumHeight(75)  # Optimized from 80px for better space efficiency
        self.version_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)  # Better responsive behavior
        self.version_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized from 30px for better space efficiency */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        self.version_input.textChanged.connect(self._validate_inputs)
        version_layout.addWidget(version_label)
        version_layout.addWidget(self.version_input)
        layout.addLayout(version_layout)
        
        # Game metadata (Type and Players)
        metadata_layout = QGridLayout()
        
        # Type field (2D/3D)
        type_label = QLabel("Type:")
        type_label.setStyleSheet("color: white; font-size: 16px;")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["2D", "3D"])
        self.type_combo.setCurrentText("2D")  # Default to 2D
        self.type_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized to 28px for better text space - matches name/version inputs */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
        """)
        
        # Players field (1 or 2)
        players_label = QLabel("Players:")
        players_label.setStyleSheet("color: white; font-size: 16px;")
        self.players_combo = QComboBox()
        self.players_combo.addItems(["1", "2"])
        self.players_combo.setCurrentText("1")  # Default to 1 player
        self.players_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 28px;  /* Optimized to 28px for better text space - matches name/version inputs */
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QComboBox::drop-down {
                border: none;
                width: 30px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
        """)
        
        # Add to grid layout
        metadata_layout.addWidget(type_label, 0, 0)
        metadata_layout.addWidget(self.type_combo, 0, 1)
        metadata_layout.addWidget(players_label, 1, 0)
        metadata_layout.addWidget(self.players_combo, 1, 1)
        metadata_layout.setSpacing(15)
        
        layout.addLayout(metadata_layout)
        
        # Categories section
        categories_layout = QVBoxLayout()
        categories_layout.setSpacing(20)
        
        # Main Categories (max 5 selections)
        main_cat_layout = QVBoxLayout()
        main_cat_label = QLabel("Main-Category (Max 5):")
        main_cat_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; margin-bottom: 15px; margin-top: 10px;")
        main_cat_label.setWordWrap(True)  # Enable text wrapping for longer labels
        
        # Create scrollable main categories list using search dialog pattern
        self.main_categories_scroll = QScrollArea()
        self.main_categories_scroll.setMaximumHeight(400)  # Increased significantly for unlimited vertical space
        self.main_categories_scroll.setWidgetResizable(True)
        self.main_categories_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        # Create widget to hold the checkboxes
        self.main_categories_widget = QWidget()
        self.main_categories_list_layout = QVBoxLayout(self.main_categories_widget)
        
        # Create checkboxes for each category
        self.main_category_checkboxes = {}
        for category in MAIN_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_main_category_changed)
            self.main_categories_list_layout.addWidget(checkbox)
            self.main_category_checkboxes[category] = checkbox
        
        # Add stretch to keep items at top
        self.main_categories_list_layout.addStretch()
        self.main_categories_scroll.setWidget(self.main_categories_widget)
        
        # Create count label for main categories
        self.main_cat_count_label = QLabel("Selected: 0/5")
        self.main_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        
        # Setup group box layout
        main_cat_group = QGroupBox("🏷️ Main Categories")
        main_cat_layout = QVBoxLayout(main_cat_group)
        main_cat_layout.addWidget(self.main_categories_scroll)
        main_cat_layout.addWidget(self.main_cat_count_label)
        main_cat_group.setLayout(main_cat_layout)
        

        # Sub Categories (unlimited selections)
        sub_cat_layout = QVBoxLayout()
        sub_cat_label = QLabel("Sub-Category (Unlimited):")
        sub_cat_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; margin-bottom: 15px; margin-top: 15px;")
        sub_cat_label.setWordWrap(True)  # Enable text wrapping for longer labels
        
        # Create scrollable sub categories list using search dialog pattern
        self.sub_categories_scroll = QScrollArea()
        self.sub_categories_scroll.setMaximumHeight(500)  # Increased significantly for unlimited vertical space
        self.sub_categories_scroll.setWidgetResizable(True)
        self.sub_categories_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        # Create widget to hold the checkboxes
        self.sub_categories_widget = QWidget()
        self.sub_categories_list_layout = QVBoxLayout(self.sub_categories_widget)
        
        # Create checkboxes for each category
        self.sub_category_checkboxes = {}
        for category in SUB_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_sub_category_changed)
            self.sub_categories_list_layout.addWidget(checkbox)
            self.sub_category_checkboxes[category] = checkbox
        
        # Add stretch to keep items at top
        self.sub_categories_list_layout.addStretch()
        self.sub_categories_scroll.setWidget(self.sub_categories_widget)
        
        # Create count label for sub categories
        self.sub_cat_count_label = QLabel("Selected: 0")
        self.sub_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        
        # Setup group box layout
        sub_cat_group = QGroupBox("🏷️ Sub Categories")
        sub_cat_layout = QVBoxLayout(sub_cat_group)
        sub_cat_layout.addWidget(self.sub_categories_scroll)
        sub_cat_layout.addWidget(self.sub_cat_count_label)
        sub_cat_group.setLayout(sub_cat_layout)
        
        # Connect signals to update count labels and enforce limits
        # Checkbox connections are set up during checkbox creation
        
        # Add to categories layout
        categories_layout.addWidget(main_cat_group)
        categories_layout.addWidget(sub_cat_group)
        
        layout.addLayout(categories_layout)
        
        # Spacer
        layout.addStretch()
        
        # Button section with extra padding to prevent collision
        button_section = QVBoxLayout()
        button_section.setSpacing(20)  # Increased from 10px to 20px space before buttons
        button_section.addStretch()  # Push buttons to bottom
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(35)  # Optimized from 40px for better space efficiency
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedSize(140, 45)  # Increased from 120x40 for better usability
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.import_button = QPushButton("Import Game")
        self.import_button.setFixedSize(180, 45)  # Increased from 150x40 for better usability
        self.import_button.setCursor(Qt.PointingHandCursor)
        self.import_button.setEnabled(True)  # Enabled by default for import
        self.import_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
            }
        """)
        self.import_button.clicked.connect(self._import_game)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        button_layout.addWidget(self.import_button)
        
        button_section.addLayout(button_layout)
        layout.addLayout(button_section)
        
        # Set dialog background
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
            QCheckBox {
                color: white;
                font-size: 13px;
            }
        """)  # Search dialog pattern styling
        
        # Set focus to name input
        self.name_input.setFocus()
        
        # Setup scroll area
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
    
    def _on_main_category_changed(self, state):
        """Handle main category selection changes and enforce 5-selection limit"""
        # Enforce 5-selection limit
        checked_count = sum(1 for checkbox in self.main_category_checkboxes.values() if checkbox.isChecked())
        
        if checked_count > 5:
            # Find and uncheck the checkbox that was just checked
            checkbox = self.sender()
            if checkbox:
                checkbox.setChecked(False)
                checked_count -= 1
            QMessageBox.information(self, "Selection Limit", "You can select a maximum of 5 main categories.")
        
        # Update count label
        self.main_cat_count_label.setText(f"Selected: {checked_count}/5")
        
        # Change color if limit reached
        if checked_count >= 5:
            self.main_cat_count_label.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px; font-weight: bold;")
        else:
            self.main_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
    
    def _on_sub_category_changed(self, state):
        """Handle sub category selection changes"""
        checked_count = sum(1 for checkbox in self.sub_category_checkboxes.values() if checkbox.isChecked())
        
        # Update count label
        self.sub_cat_count_label.setText(f"Selected: {checked_count}")
    
    def _validate_inputs(self):
        """Enable/disable Import button based on input validity"""
        name_text = self.name_input.text().strip()
        if name_text and len(name_text) >= 1:
            self.import_button.setEnabled(True)
        else:
            self.import_button.setEnabled(False)
    
    def _import_game(self):
        name = self.name_input.text().strip()
        version = self.version_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Invalid Input", "Please enter a game name.")
            return
        
        if not version:
            version = "1.0.0"
        
        # Get selected categories from checkboxes
        selected_main_categories = []
        for category, checkbox in self.main_category_checkboxes.items():
            if checkbox.isChecked():
                selected_main_categories.append(category)
        
        selected_sub_categories = []
        for category, checkbox in self.sub_category_checkboxes.items():
            if checkbox.isChecked():
                selected_sub_categories.append(category)
        
        self.game_data = {
            "name": name, 
            "version": version, 
            "type": self.type_combo.currentText(), 
            "players": self.players_combo.currentText(),
            "main_categories": selected_main_categories,
            "sub_categories": selected_sub_categories
        }
        self.accept()


class AIGameImportDialog(QDialog):
    """AI-powered dialog for importing games with intelligent manifest generation"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Import Game")
        self.setFixedSize(600, 630)
        self.setModal(True)
        self.game_data = None
        self.html_content = None
        self.selected_file_path = None
        self.ai_processing = False
        self.imported_game_name = None  # Store the name of imported game for highlighting
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup AI import dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title_label = QLabel("🤖 AI-Powered Game Import")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #E5E5E5; margin: 10px;")
        layout.addWidget(title_label)
        
        # Info text
        info_label = QLabel("Select an HTML game file and AI will analyze it to automatically generate game metadata and categories.")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 14px; color: #E5E5E5; margin-bottom: 20px;")
        layout.addWidget(info_label)
        
        # File selection section
        file_section = QGroupBox("Game File Selection")
        file_layout = QVBoxLayout(file_section)
        
        # Selected file display
        self.selected_file_label = QLabel("No file selected")
        self.selected_file_label.setStyleSheet("color: #888; font-style: italic; padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
        self.selected_file_label.setWordWrap(True)
        file_layout.addWidget(self.selected_file_label)
        
        # Select file button
        self.select_file_button = QPushButton("Select HTML Game File")
        self.select_file_button.setFixedHeight(40)
        self.select_file_button.setCursor(Qt.PointingHandCursor)
        self.select_file_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: white;
                padding: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.select_file_button.clicked.connect(self._select_html_file)
        file_layout.addWidget(self.select_file_button)
        
        layout.addWidget(file_section)
        
        # AI Analysis section
        analysis_section = QGroupBox("AI Analysis")
        analysis_layout = QVBoxLayout(analysis_section)
        
        # Analysis status
        self.analysis_status = QLabel("Ready to analyze with AI")
        self.analysis_status.setStyleSheet("color: #888; font-size: 14px; padding: 10px;")
        analysis_layout.addWidget(self.analysis_status)
        
        # Analyze button
        self.analyze_button = QPushButton("🤖 Analyze with AI")
        self.analyze_button.setFixedHeight(40)
        self.analyze_button.setEnabled(False)
        self.analyze_button.setCursor(Qt.PointingHandCursor)
        self.analyze_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: white;
                padding: 10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.analyze_button.clicked.connect(self._analyze_with_ai)
        analysis_layout.addWidget(self.analyze_button)
        
        layout.addWidget(analysis_section)
        
        # Generated metadata display
        self.metadata_display = QTextEdit()
        self.metadata_display.setMaximumHeight(150)
        self.metadata_display.setReadOnly(True)
        self.metadata_display.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                padding: 10px;
            }
        """)
        self.metadata_display.setPlaceholderText("AI-generated manifest.json will appear here...")
        layout.addWidget(self.metadata_display)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedHeight(35)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        button_layout.addStretch()
        
        self.import_button = QPushButton("Import Game")
        self.import_button.setFixedHeight(35)
        self.import_button.setEnabled(False)
        self.import_button.setCursor(Qt.PointingHandCursor)
        self.import_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #333333, stop:1 #2a2a2a);
                border: 2px solid #555555;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: #E5E5E5;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #2a2a2a, stop:0.3 #333333, stop:0.7 #3a3a3a, stop:1 #2a2a2a);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555555;
                color: #E5E5E5;
            }
        """)
        self.import_button.clicked.connect(self._import_game)
        button_layout.addWidget(self.import_button)
        
        layout.addLayout(button_layout)
        
        # Set dialog background
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
        """)
    
    def _select_html_file(self):
        """Open file dialog to select HTML game file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select HTML Game File",
            "",
            "HTML Files (*.html *.htm);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            # Validate that it's HTML content
            with open(file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            if not html_content.strip().lower().startswith('<!doctype') and '<html' not in html_content.lower():
                QMessageBox.warning(
                    self, 
                    "Invalid File", 
                    "Selected file does not appear to be a valid HTML file."
                )
                return
            
            # Store file information
            self.selected_file_path = file_path
            self.html_content = html_content
            
            # Update UI
            file_name = Path(file_path).name
            self.selected_file_label.setText(f"Selected: {file_name}")
            self.selected_file_label.setStyleSheet("color: #E5E5E5; font-weight: bold; padding: 10px; background-color: #2a2a2a; border-radius: 5px;")
            
            self.analyze_button.setEnabled(True)
            self.analysis_status.setText("Ready to analyze with AI")
            self.analysis_status.setStyleSheet("color: #E5E5E5; font-size: 14px; padding: 10px;")
            
            # Clear previous metadata
            self.metadata_display.clear()
            self.import_button.setEnabled(False)
            
        except Exception as e:
            QMessageBox.critical(self, "File Error", f"Failed to read file: {e}")
    
    def _analyze_with_ai(self):
        """Analyze HTML content with AI to generate manifest.json"""
        if not self.html_content:
            return
        
        self.ai_processing = True
        self.analyze_button.setEnabled(False)
        self.analyze_button.setText("🤖 Analyzing...")
        self.analysis_status.setText("AI is analyzing your game file...")
        self.analysis_status.setStyleSheet("color: #E5E5E5; font-size: 14px; padding: 10px; font-weight: bold;")
        
        # Use QTimer to run AI analysis in background thread
        QTimer.singleShot(100, self._run_ai_analysis)
    
    def _run_ai_analysis(self):
        """Run AI analysis in background"""
        try:
            # Create AI prompt for manifest generation
            ai_prompt = self._create_ai_prompt(self.html_content)
            
            # Get AI model
            model, model_name = create_gamai_model()
            if not model:
                raise Exception("AI model not available. Please check your API key configuration.")
            
            # Generate response
            response = model.generate_content(ai_prompt)
            ai_response = response.text
            
            # Parse AI response
            manifest_data = self._parse_ai_response(ai_response)
            
            if manifest_data:
                # Update UI with generated metadata
                self._display_generated_metadata(manifest_data)
                self.analysis_status.setText("✅ AI analysis completed successfully!")
                self.analysis_status.setStyleSheet("color: #E5E5E5; font-size: 14px; padding: 10px; font-weight: bold;")
                self.import_button.setEnabled(True)
                
                # Store for import
                self.game_data = manifest_data
            else:
                raise Exception("Failed to parse AI response")
                
        except Exception as e:
            self.analysis_status.setText(f"❌ AI analysis failed: {str(e)}")
            self.analysis_status.setStyleSheet("color: #E5E5E5; font-size: 14px; padding: 10px;")
            QMessageBox.warning(self, "AI Analysis Failed", f"AI could not analyze the file: {str(e)}")
        
        finally:
            # Reset UI state
            self.ai_processing = False
            self.analyze_button.setEnabled(True)
            self.analyze_button.setText("🤖 Analyze with AI")
    
    def _create_ai_prompt(self, html_content):
        """Create AI prompt for manifest generation"""
        # Truncate HTML if too long (keep reasonable length for AI processing)
        if len(html_content) > 8000:
            html_content = html_content[:4000] + "\n... [content truncated] ...\n" + html_content[-4000:]
        
        prompt = f"""ANALYZE THE FOLLOWING HTML GAME FILE AND GENERATE MANIFEST.JSON CONTENT:

index.html content:
{html_content}

INSTRUCTIONS:
1. Analyze if this HTML content represents a game
2. If NOT a game, select main category as "tools"
3. If it IS a game, provide appropriate categories
4. List game types and player count you identify
5. Enumerate all game files (what game names exist in the HTML)
6. Ensure name uniqueness - if name exists, add numbers (game1, game2, game3)
7. Version is always "1.0.0" for AI imports

AVAILABLE MAIN CATEGORIES (choose up to 5):
- action: Action games (shooters, fighters, platformers)
- adventure: Adventure games (story-driven, exploration)
- arcade: Classic arcade games (retro style, simple controls)
- puzzle: Puzzle games (brain teasers, match-3, logic)
- strategy: Strategy games (tower defense, RTS, turn-based)
- sports: Sports games (football, basketball, racing)
- simulation: Simulation games (flight, city building, life)
- racing: Racing games (cars, motorcycles, vehicles)
- fighting: Fighting games (combat, martial arts)
- shooting: Shooting games (first-person, third-person)
- platformer: Platform games (jump and run, side-scrolling)
- rpg: Role-playing games (character progression, story)
- survival: Survival games (resource management, crafting)
- horror: Horror games (scary, survival horror)
- educational: Educational games (learning, training)
- casual: Casual games (simple, quick play)
- music: Music games (rhythm, instruments)
- card: Card games (poker, solitaire, trading cards)
- casino: Casino games (slots, gambling)
- board: Board games (chess, checkers, strategy board)
- trivia: Quiz games (questions, answers, knowledge)
- word: Word games (spelling, vocabulary, crosswords)
- tools: Utility tools (calculators, converters, editors)

SUB CATEGORIES (specific types under main categories):
- For action: combat, platform, stealth, hack-and-slash
- For puzzle: logic, match-3, brain-teaser, word-puzzle
- For strategy: tower-defense, rts, turn-based, resource-management
- For sports: team-sports, individual-sports, racing, Olympics
- For simulation: flight, city-building, life-simulation, vehicle
- For arcade: retro, classic, simple-controls, scoring
- For adventure: story-driven, exploration, point-and-click, narrative
- For racing: cars, motorcycles, boats, futuristic
- For fighting: martial-arts, weapons, 1v1, tournament
- For shooting: fps, tps, laser, projectile
- For platformer: side-scrolling, jump-and-run, precision, retro
- For rpg: fantasy, sci-fi, turn-based, action-rpg
- For survival: crafting, zombie, post-apocalyptic, resource-gathering
- For horror: psychological, survival, jump-scare, atmospheric
- For educational: math, language, science, history
- For casual: simple, quick, relaxing, family-friendly
- For music: rhythm, instruments, karaoke, dance
- For card: solitaire, poker, trading-card, collectible
- For casino: slots, poker, roulette, betting
- For board: chess, checkers, go, strategy-board
- For trivia: general-knowledge, specific-topics, rapid-fire, quiz
- For word: spelling, vocabulary, anagrams, crosswords
- For tools: calculator, text-editor, converter, utility

VALID MANIFEST.JSON FORMAT:
{{
  "name": "Game Name",
  "version": "1.0.0",
  "main_categories": ["category1", "category2"],
  "sub_categories": ["subcategory1", "subcategory2"]
}}

IMPORTANT RULES:
- Use ONLY the main categories listed above
- Use ONLY the sub categories listed above  
- Maximum 5 main categories
- Sub categories should relate to main categories chosen
- If no specific category fits, use "tools"
- Ensure JSON format is valid
- Respond ONLY with the JSON content, no additional text

RESPOND ONLY WITH THE JSON FORMAT ABOVE, NOTHING ELSE:
"""
        return prompt
    
    def _parse_ai_response(self, ai_response):
        """Parse AI response to extract manifest data"""
        try:
            # Extract JSON from AI response
            # Look for JSON content between { and }
            start_idx = ai_response.find('{')
            end_idx = ai_response.rfind('}')
            
            if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
                raise Exception("No valid JSON found in AI response")
            
            json_str = ai_response[start_idx:end_idx + 1]
            
            # Parse JSON
            manifest_data = json.loads(json_str)
            
            # Validate required fields
            required_fields = ['name', 'version', 'main_categories', 'sub_categories']
            for field in required_fields:
                if field not in manifest_data:
                    raise Exception(f"Missing required field: {field}")
            
            # Ensure version is always 1.0.0 for AI imports
            manifest_data['version'] = '1.0.0'
            
            # Validate categories are lists
            if not isinstance(manifest_data['main_categories'], list):
                manifest_data['main_categories'] = [manifest_data['main_categories']]
            if not isinstance(manifest_data['sub_categories'], list):
                manifest_data['sub_categories'] = [manifest_data['sub_categories']]
            
            # Add system-managed fields for compatibility
            manifest_data['type'] = '2D'  # Default for AI imports
            manifest_data['players'] = '1'  # Default for AI imports
            
            return manifest_data
            
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in AI response: {e}")
        except Exception as e:
            raise Exception(f"Error parsing AI response: {e}")
    
    def _display_generated_metadata(self, manifest_data):
        """Display generated metadata in the UI"""
        # Create formatted display
        display_text = f"🤖 AI Generated Metadata:\n\n"
        display_text += f"Name: {manifest_data['name']}\n"
        display_text += f"Version: {manifest_data['version']}\n"
        display_text += f"Type: {manifest_data['type']}\n"
        display_text += f"Players: {manifest_data['players']}\n"
        display_text += f"Main Categories: {', '.join(manifest_data['main_categories'])}\n"
        display_text += f"Sub Categories: {', '.join(manifest_data['sub_categories'])}\n\n"
        display_text += "📄 JSON Format:\n"
        display_text += json.dumps(manifest_data, indent=2)
        
        self.metadata_display.setPlainText(display_text)
    
    def _import_game(self):
        """Import game using AI-generated metadata"""
        if not self.game_data or not self.html_content:
            QMessageBox.warning(self, "Import Error", "No game data or HTML content available for import.")
            return
        
        try:
            # Validate generated name
            if not self.game_data.get('name', '').strip():
                QMessageBox.warning(self, "Import Error", "AI generated an invalid game name.")
                return
            
            # Get main window to access game service
            main_window = self.parent()
            if not main_window or not hasattr(main_window, 'game_service'):
                QMessageBox.critical(self, "Import Error", "Game service not available.")
                return
            
            # Import the game using AI-generated metadata
            new_game = main_window.game_service.import_game(
                self.html_content,
                self.game_data['name'],
                self.game_data['version'],
                main_categories=self.game_data['main_categories'],
                sub_categories=self.game_data['sub_categories']
            )
            
            if new_game:
                # Show success message
                QMessageBox.information(
                    self, 
                    "Import Successful", 
                    f"✅ Game '{self.game_data['name']}' imported successfully using AI analysis!\n\n"
                    f"The game has been automatically categorized and added to your collection."
                )
                
                # Reload games and update display
                if hasattr(main_window, 'game_service') and hasattr(main_window, 'game_list'):
                    # Get updated games list from service
                    updated_games = main_window.game_service.discover_games()
                    # Update main window's games list
                    main_window.games = updated_games
                    # Update display
                    if hasattr(main_window, 'is_filtered') and main_window.is_filtered and hasattr(main_window, 'current_filtered_games'):
                        if main_window.current_filtered_games:
                            main_window.game_list.display_games(main_window.current_filtered_games)
                        else:
                            main_window.game_list.display_games(updated_games)
                    else:
                        main_window.game_list.display_games(updated_games)
                    
                    # Store the imported game name for highlighting
                    self.imported_game_name = self.game_data['name']
                    # Trigger highlighting after UI update
                    QTimer.singleShot(500, lambda: main_window.game_list.highlight_game(self.imported_game_name) if main_window.game_list else None)
                
                # Accept the dialog
                self.accept()
            else:
                QMessageBox.critical(self, "Import Error", "Failed to import the game.")
                
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Error importing game: {str(e)}")


class FeedbackDialog(QDialog):
    """Dialog for managing game feedback with scrollable sub-boxes"""
    
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setWindowTitle(f"Feedback Manager - {game.name}")
        self.setFixedSize(800, 700)  # Fixed size with scrollable content
        self.setModal(True)
        self.sub_boxes = []  # Store references to sub-box widgets
        self._setup_ui()
        self._load_existing_feedback()
    
    def _setup_ui(self):
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title section
        title_label = QLabel("Feedback Manager")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("""
            font-size: 28px;
            font-weight: bold;
            color: white;
            padding: 20px;
            background-color: #1a1a1a;
        """)
        main_layout.addWidget(title_label)
        
        # Instructions
        instructions_label = QLabel("Click + to add feedback (100 characters max)\nClick Edit/Delete to manage existing feedback")
        instructions_label.setAlignment(Qt.AlignCenter)
        instructions_label.setStyleSheet("""
            color: #888;
            font-size: 14px;
            padding: 10px;
            background-color: #1a1a1a;
        """)
        main_layout.addWidget(instructions_label)
        
        # Scroll area for feedback sub-boxes
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #1a1a1a;
            }
            QScrollBar:vertical {
                background: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #E5E5E5;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #E5E5E5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Content widget for feedback sub-boxes
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(15)
        content_layout.setContentsMargins(30, 20, 30, 30)
        
        # Create 10 feedback sub-boxes
        for i in range(10):
            sub_box = self._create_feedback_sub_box(i)
            self.sub_boxes.append(sub_box)
            content_layout.addWidget(sub_box)
        
        # Add stretch to keep content at top
        content_layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # Set background
        self.setStyleSheet("background-color: #1a1a1a;")
    
    def _create_feedback_sub_box(self, index):
        """Create a single feedback sub-box using inline text editing (like game name box)"""
        group = QGroupBox(f"Feedback {index + 1}")
        group.setStyleSheet("""
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                color: white;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                min-height: 140px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px 0 8px;
                background-color: #1a1a1a;
                color: #E5E5E5;
            }
        """)
        
        # Layout for sub-box content
        box_layout = QVBoxLayout(group)
        box_layout.setContentsMargins(15, 10, 15, 15)
        box_layout.setSpacing(10)
        
        # Create text input area (always visible, like game name box)
        text_input = QLineEdit("")
        text_input.setPlaceholderText("Enter feedback (100 characters max)")
        text_input.setMinimumHeight(75)
        text_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 12px;
                color: white;
                font-size: 16px;
                font-weight: bold;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        
        # Character counter and buttons
        counter_button_layout = QHBoxLayout()
        counter_button_layout.setSpacing(10)
        
        char_counter = QLabel("0/100")
        char_counter.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        char_counter.setAlignment(Qt.AlignRight)
        
        # Save button (replaces Ok button)
        save_button = QPushButton("Save")
        save_button.setFixedSize(100, 40)
        save_button.setCursor(Qt.PointingHandCursor)
        save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        save_button.clicked.connect(lambda: self._save_feedback_direct(index, text_input.text()))
        save_button.setEnabled(False)  # Disabled until valid input
        
        # Edit and Delete buttons
        edit_button = QPushButton("Edit")
        edit_button.setFixedSize(80, 35)
        edit_button.setCursor(Qt.PointingHandCursor)
        edit_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        edit_button.clicked.connect(lambda: self._enable_editing(index, text_input))
        
        delete_button = QPushButton("Delete")
        delete_button.setFixedSize(80, 35)
        delete_button.setCursor(Qt.PointingHandCursor)
        delete_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        delete_button.clicked.connect(lambda: self._delete_feedback_direct(index))
        
        # Show/hide buttons based on current state
        edit_button.setVisible(False)
        delete_button.setVisible(False)
        
        # Add widgets to layout
        box_layout.addWidget(text_input)
        
        counter_button_layout.addWidget(char_counter)
        counter_button_layout.addWidget(save_button)
        counter_button_layout.addWidget(edit_button)
        counter_button_layout.addWidget(delete_button)
        box_layout.addLayout(counter_button_layout)
        
        # Connect text changed signal for real-time validation
        text_input.textChanged.connect(lambda text: self._validate_feedback_input(index, text, char_counter, save_button))
        
        # Store references
        group.text_input = text_input
        group.char_counter = char_counter
        group.save_button = save_button
        group.edit_button = edit_button
        group.delete_button = delete_button
        
        return group
    
    def _update_char_counter_for_box(self, box_index):
        """Update character counter for specific sub-box"""
        if box_index < len(self.sub_boxes):
            sub_box = self.sub_boxes[box_index]
            text = sub_box.content_area.toPlainText()
            # Remove newlines
            text = text.replace('\n', '')
            if text != sub_box.content_area.toPlainText():
                cursor = sub_box.content_area.textCursor()
                sub_box.content_area.setPlainText(text)
                sub_box.content_area.setTextCursor(cursor)
            
            char_count = len(text)
            sub_box.char_counter.setText(f"{char_count}/100")
            
            # Enable/disable Ok button based on content
            sub_box.ok_button.setEnabled(char_count > 0 and char_count <= 100)
    
    def _update_char_counter(self):
        """Update character counter and Ok button state (legacy method)"""
        if hasattr(self, 'content_area'):
            text = self.content_area.toPlainText()
            # Remove newlines
            text = text.replace('\n', '')
            if text != self.content_area.toPlainText():
                cursor = self.content_area.textCursor()
                self.content_area.setPlainText(text)
                self.content_area.setTextCursor(cursor)
            
            char_count = len(text)
            self.char_counter.setText(f"{char_count}/100")
            
            # Enable/disable Ok button based on content
            if hasattr(self, 'ok_button'):
                self.ok_button.setEnabled(char_count > 0 and char_count <= 100)
    
    def _show_input_mode(self, index):
        """Show input mode for adding new feedback"""
        if index < len(self.sub_boxes):
            sub_box = self.sub_boxes[index]
            
            # Clear input area
            sub_box.content_area.setPlainText("")
            sub_box.char_counter.setText("0/100")
            sub_box.ok_button.setEnabled(False)
            
            # Show input elements first
            sub_box.empty_widget.hide()  # Hide the empty state
            sub_box.content_area.show()  # Show text input
            sub_box.content_area.setEnabled(True)  # Ensure it's enabled
            sub_box.char_counter.show()  # Show character counter
            sub_box.ok_button.show()  # Show Ok button
            
            # Hide management elements
            sub_box.edit_button.hide()
            sub_box.delete_button.hide()
            
            # Remove any display label first
            layout = sub_box.layout()
            for j in range(layout.count()):
                item = layout.itemAt(j)
                if item and item.widget() and hasattr(item.widget(), 'setStyleSheet') and 'background-color: #2a2a2a' in item.widget().styleSheet():
                    widget = item.widget()
                    layout.removeItem(item)
                    widget.setParent(None)
            
            # Focus on input area
            sub_box.content_area.setFocus()
            
            # Force update to ensure changes are visible
            sub_box.updateGeometry()
            sub_box.repaint()
    
    def _save_feedback(self, index):
        """Save feedback for the specified index"""
        if index < len(self.sub_boxes):
            sub_box = self.sub_boxes[index]
            text = sub_box.content_area.toPlainText().strip()
            
            if text and len(text) <= 100:
                # Remove newlines if any
                text = text.replace('\n', '')
                
                # If editing existing feedback or adding new one
                if index < len(self.game.feedback):
                    # Edit existing feedback
                    self.game.edit_feedback(index, text)
                else:
                    # Add new feedback
                    self.game.add_feedback(text)
                
                # Update UI to show saved feedback
                self._update_sub_box_display(index, text)
                # No need to refresh all displays since we only updated one
    
    def _edit_feedback(self, index):
        """Enable editing mode for existing feedback"""
        if index < len(self.sub_boxes):
            sub_box = self.sub_boxes[index]
            feedback_text = self.game.feedback[index]
            
            # Remove any display label first
            layout = sub_box.layout()
            for j in range(layout.count()):
                item = layout.itemAt(j)
                if item and item.widget() and hasattr(item.widget(), 'setStyleSheet') and 'background-color: #2a2a2a' in item.widget().styleSheet():
                    widget = item.widget()
                    layout.removeItem(item)
                    widget.setParent(None)
            
            # Show input elements, hide management elements
            sub_box.empty_widget.hide()  # Hide empty state
            sub_box.content_area.setPlainText(feedback_text)
            sub_box.content_area.show()
            sub_box.content_area.setEnabled(True)
            sub_box.char_counter.show()
            sub_box.ok_button.show()
            sub_box.edit_button.hide()
            sub_box.delete_button.hide()
            
            # Update character counter
            sub_box.char_counter.setText(f"{len(feedback_text)}/100")
            sub_box.ok_button.setEnabled(True)
            
            # Focus on input area
            sub_box.content_area.setFocus()
            sub_box.content_area.setFocus()
    
    def _delete_feedback(self, index):
        """Delete feedback at the specified index"""
        reply = QMessageBox.question(self, "Delete Feedback", 
                                   "Are you sure you want to delete this feedback?",
                                   QMessageBox.Yes | QMessageBox.No, 
                                   QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.game.delete_feedback(index)
            self._refresh_all_displays()
    
    def _load_existing_feedback(self):
        """Load existing feedback into sub-boxes (simplified for inline editing)"""
        for i, feedback_text in enumerate(self.game.feedback):
            if i < len(self.sub_boxes):
                # Convert each sub-box to display mode with existing feedback
                self._convert_to_display_mode(i, feedback_text)
        
        # All sub-boxes start with text input visible and ready for new feedback
    
    def _update_sub_box_display(self, index, feedback_text):
        """Update sub-box to show feedback text in display mode"""
        if index < len(self.sub_boxes):
            sub_box = self.sub_boxes[index]
            
            # Create display label with better text formatting (20 chars per line, 5 lines)
            # Break text into lines of 20 characters max
            lines = []
            for i in range(0, len(feedback_text), 20):
                lines.append(feedback_text[i:i+20])
            
            # Join with line breaks and limit to 5 lines
            display_text = '\n'.join(lines[:5])
            if len(lines) > 5:
                display_text += '\n...'  # Indicate truncated text
            
            display_label = QLabel(display_text)
            display_label.setStyleSheet("""
                color: white;
                font-size: 14px;
                padding: 10px;
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                line-height: 1.4;
            """)
            display_label.setWordWrap(True)
            display_label.setAlignment(Qt.AlignTop)
            display_label.setMaximumHeight(120)  # Allow for 5 lines
            
            # Hide all elements first
            sub_box.empty_widget.hide()
            sub_box.content_area.hide()
            sub_box.char_counter.hide()
            sub_box.ok_button.hide()
            
            # Show management elements
            sub_box.edit_button.show()
            sub_box.delete_button.show()
            
            # Replace any existing display label
            layout = sub_box.layout()
            # Remove old display label if it exists
            for i in range(layout.count()):
                item = layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'setStyleSheet') and 'background-color: #2a2a2a' in item.widget().styleSheet():
                    layout.removeItem(item)
                    old_widget = item.widget()
                    old_widget.setParent(None)
            
            # Add new display label
            layout.insertWidget(1, display_label)  # Position 1 (after empty widget at 0)
            sub_box.display_label = display_label
    
    # Removed _refresh_all_displays method as it's replaced by _load_existing_feedback

    def _validate_feedback_input(self, box_index, text, char_counter, save_button):
        """Validate feedback input in real-time and update counter"""
        # Update character counter
        char_count = len(text)
        char_counter.setText(f"{char_count}/100")
        
        # Enable/disable save button based on valid input
        if char_count > 0 and char_count <= 100:
            save_button.setEnabled(True)
            char_counter.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px;")
        else:
            save_button.setEnabled(False)
            if char_count > 100:
                char_counter.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px;")
            else:
                char_counter.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
    
    def _save_feedback_direct(self, index, text):
        """Save feedback directly from QLineEdit input"""
        text = text.strip()
        if text and len(text) <= 100:
            try:
                if index < len(self.game.feedback):
                    # Edit existing feedback
                    self.game.edit_feedback(index, text)
                else:
                    # Add new feedback
                    self.game.add_feedback(text)
                
                # Update UI to show saved feedback (convert to read-only display)
                self._convert_to_display_mode(index, text)
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save feedback: {e}")
    
    def _convert_to_display_mode(self, index, text):
        """Convert QLineEdit to read-only display mode"""
        if index < len(self.sub_boxes):
            sub_box = self.sub_boxes[index]
            
            # Convert to read-only text display
            sub_box.text_input.setReadOnly(True)
            sub_box.text_input.setText(text)
            sub_box.text_input.setStyleSheet("""
                QLineEdit {
                    background-color: #1e1e1e;
                    border: 2px solid #3a3a3a;
                    border-radius: 8px;
                    padding: 12px;
                    color: #E5E5E5;
                    font-size: 16px;
                    font-weight: bold;
                }
            """)
            
            # Hide save button, show edit/delete buttons
            sub_box.save_button.setVisible(False)
            sub_box.edit_button.setVisible(True)
            sub_box.delete_button.setVisible(True)
            
            # Update character counter for display
            sub_box.char_counter.setText(f"{len(text)}/100")
            sub_box.char_counter.setStyleSheet("color: #E5E5E5; font-size: 12px; margin-top: 5px;")
    
    def _enable_editing(self, index, text_input):
        """Enable editing mode for existing feedback"""
        if index < len(self.sub_boxes):
            sub_box = self.sub_boxes[index]
            
            # Make text input editable again
            text_input.setReadOnly(False)
            text_input.setStyleSheet("""
                QLineEdit {
                    background-color: #2a2a2a;
                    border: 2px solid #E5E5E5;
                    border-radius: 8px;
                    padding: 12px;
                    color: white;
                    font-size: 16px;
                    font-weight: bold;
                }
                QLineEdit:focus {
                    border-color: #E5E5E5;
                    background-color: #333333;
                }
            """)
            
            # Show save button, hide edit/delete buttons
            sub_box.save_button.setVisible(True)
            sub_box.edit_button.setVisible(False)
            sub_box.delete_button.setVisible(False)
            
            # Focus on text input
            text_input.setFocus()
            text_input.selectAll()
    
    def _delete_feedback_direct(self, index):
        """Delete feedback and reset to empty state"""
        if index < len(self.sub_boxes):
            try:
                if index < len(self.game.feedback):
                    self.game.delete_feedback(index)
                    
                # Reset to empty state
                sub_box = self.sub_boxes[index]
                sub_box.text_input.setText("")
                sub_box.text_input.setReadOnly(False)
                sub_box.text_input.setStyleSheet("""
                    QLineEdit {
                        background-color: #2a2a2a;
                        border: 2px solid #3a3a3a;
                        border-radius: 8px;
                        padding: 12px;
                        color: white;
                        font-size: 16px;
                        font-weight: bold;
                    }
                    QLineEdit:focus {
                        border-color: #E5E5E5;
                        background-color: #333333;
                    }
                """)
                
                # Reset buttons
                sub_box.save_button.setVisible(False)
                sub_box.edit_button.setVisible(False)
                sub_box.delete_button.setVisible(False)
                
                # Reset counter
                sub_box.char_counter.setText("0/100")
                sub_box.char_counter.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete feedback: {e}")


class OneShotGameDialog(QDialog):
    """Dialog for creating games with AI-powered generation from user inputs"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("One-Shot AI Game Creation")
        self.setFixedSize(800, 800)  # Increased size for better UX with scrolling
        self.setModal(True)
        self.generated_game_name = None
        self.generation_thread = None  # Track running thread
        self.ai_content = None  # Store generated AI content
        self._setup_ui()
    
    def closeEvent(self, event):
        """Handle dialog close - clean up thread if running"""
        if hasattr(self, 'generation_thread') and self.generation_thread is not None:
            if self.generation_thread.isRunning():
                self.generation_thread.quit()
                self.generation_thread.wait()
                self.generation_thread = None
        event.accept()
    
    def _setup_ui(self):
        # Main scrollable layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Content widget for scrolling
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("Create Complete Game with AI")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 20px; color: #CCCCCC;")
        layout.addWidget(title_label)
        
        # Game Name Section
        name_group = QGroupBox("Game Information")
        name_layout = QVBoxLayout(name_group)
        
        name_layout.addWidget(QLabel("Game Name:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter your game name...")
        self.name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 15px;
                color: white;
                font-size: 14px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        self.name_input.textChanged.connect(self._validate_inputs)
        name_layout.addWidget(self.name_input)
        
        # Version (read-only)
        version_layout = QHBoxLayout()
        version_layout.addWidget(QLabel("Version:"))
        self.version_label = QLabel("0.0.1")
        self.version_label.setStyleSheet("font-weight: bold; color: #E5E5E5;")
        version_layout.addWidget(self.version_label)
        version_layout.addStretch()
        name_layout.addLayout(version_layout)
        
        # Type and Players
        type_players_layout = QHBoxLayout()
        
        type_layout = QVBoxLayout()
        type_layout.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["2D", "3D"])
        self.type_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 5px;
                color: white;
                font-size: 14px;
                min-width: 80px;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #3a3a3a;
                selection-background-color: #E5E5E5;
                selection-color: black;
            }
        """)
        type_layout.addWidget(self.type_combo)
        type_players_layout.addLayout(type_layout)
        
        players_layout = QVBoxLayout()
        players_layout.addWidget(QLabel("Players:"))
        self.players_combo = QComboBox()
        self.players_combo.addItems(["1", "2"])
        self.players_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 5px;
                color: white;
                font-size: 14px;
                min-width: 80px;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #3a3a3a;
                selection-background-color: #E5E5E5;
                selection-color: black;
            }
        """)
        players_layout.addWidget(self.players_combo)
        type_players_layout.addLayout(players_layout)
        
        type_players_layout.addStretch()
        name_layout.addLayout(type_players_layout)
        
        layout.addWidget(name_group)
        
        # Categories Section
        categories_group = QGroupBox("Categories")
        categories_layout = QVBoxLayout(categories_group)
        
        # Main Categories - Allow 1-5 selections
        main_cat_group = QGroupBox("🏷️ Main Categories (Select 1-5)")
        main_cat_layout = QVBoxLayout(main_cat_group)
        
        # Create scroll area for main categories
        main_cat_scroll = QScrollArea()
        main_cat_scroll.setMaximumHeight(200)
        main_cat_scroll.setWidgetResizable(True)
        main_cat_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        main_cat_widget = QWidget()
        self.main_categories_list_layout = QVBoxLayout(main_cat_widget)
        
        # Create checkboxes for main categories
        self.main_category_checkboxes = {}
        for category in MAIN_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_main_category_changed)
            self.main_categories_list_layout.addWidget(checkbox)
            self.main_category_checkboxes[category] = checkbox
        
        # Add stretch to keep items at top
        self.main_categories_list_layout.addStretch()
        main_cat_scroll.setWidget(main_cat_widget)
        main_cat_layout.addWidget(main_cat_scroll)
        
        # Create count label for main categories
        self.main_cat_count_label = QLabel("Selected: 0/5")
        self.main_cat_count_label.setStyleSheet("color: #888; font-size: 12px; margin-top: 5px;")
        main_cat_layout.addWidget(self.main_cat_count_label)
        
        categories_layout.addWidget(main_cat_group)
        
        # Sub Categories - Optional
        sub_cat_group = QGroupBox("🏷️ Sub Categories (Optional)")
        sub_cat_layout = QVBoxLayout(sub_cat_group)
        
        # Create scroll area for sub categories
        sub_cat_scroll = QScrollArea()
        sub_cat_scroll.setMaximumHeight(250)
        sub_cat_scroll.setWidgetResizable(True)
        sub_cat_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        sub_cat_widget = QWidget()
        self.sub_categories_list_layout = QVBoxLayout(sub_cat_widget)
        
        # Create checkboxes for sub categories
        self.sub_category_checkboxes = {}
        for category in SUB_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            self.sub_categories_list_layout.addWidget(checkbox)
            self.sub_category_checkboxes[category] = checkbox
        
        # Add stretch to keep items at top
        self.sub_categories_list_layout.addStretch()
        sub_cat_scroll.setWidget(sub_cat_widget)
        sub_cat_layout.addWidget(sub_cat_scroll)
        
        categories_layout.addWidget(sub_cat_group)
        
        layout.addWidget(categories_group)
        
        # User Prompt Section
        prompt_group = QGroupBox("Custom Instructions (Optional)")
        prompt_layout = QVBoxLayout(prompt_group)
        
        self.prompt_input = QTextEdit()
        self.prompt_input.setPlaceholderText("Describe your game vision, specific features, levels, mechanics, etc.\nExample: 'Make a platformer with 10 levels and a final boss battle with special effects'")
        self.prompt_input.setMaximumHeight(80)
        self.prompt_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
                color: white;
            }
            QTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        prompt_layout.addWidget(self.prompt_input)
        
        layout.addWidget(prompt_group)
        
        # AI Content Display Area
        content_group = QGroupBox("AI Generated Content")
        content_layout = QVBoxLayout(content_group)
        
        self.ai_content_display = QTextEdit()
        self.ai_content_display.setReadOnly(True)
        self.ai_content_display.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 2px solid #ddd;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
                color: #333;
            }
        """)
        self.ai_content_display.setPlaceholderText("AI generated game content will appear here...\n\nStep 1: Click 'Generate Game' to create content\nStep 2: Review the content below\nStep 3: Click 'Apply' to create your game")
        content_layout.addWidget(self.ai_content_display)
        
        layout.addWidget(content_group)
        
        # Button Section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)
        
        # Generate Button
        self.generate_button = QPushButton("🎮 Generate Game")
        self.generate_button.setFixedSize(200, 50)
        self.generate_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #666;
                color: #999;
            }
        """)
        self.generate_button.clicked.connect(self._generate_game)
        self.generate_button.setEnabled(False)  # Initially disabled
        button_layout.addWidget(self.generate_button)
        
        # Apply Button
        self.apply_button = QPushButton("✅ Apply & Create Game")
        self.apply_button.setFixedSize(200, 50)
        self.apply_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.apply_button.clicked.connect(self._apply_game)
        self.apply_button.setEnabled(False)  # Initially disabled until content is generated
        button_layout.addWidget(self.apply_button)
        
        layout.addLayout(button_layout)
        
        # Instructions
        instructions_label = QLabel("Step 1: Fill in required fields (Game Name + Main Category)\nStep 2: Click 'Generate Game' to create AI content\nStep 3: Review the generated content\nStep 4: Click 'Apply & Create Game' to finalize")
        instructions_label.setAlignment(Qt.AlignCenter)
        instructions_label.setStyleSheet("font-size: 12px; color: #666; margin-top: 15px; padding: 10px; background-color: #E5E5E5; border-radius: 5px;")
        layout.addWidget(instructions_label)
        
        # Add stretch to push content to top
        layout.addStretch()
        
        # Set up scroll area
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
    
    def _validate_inputs(self):
        """Enable/disable generate button based on input validation"""
        has_name = bool(self.name_input.text().strip())
        # Check if at least 1 main category is selected
        has_main_category = sum(1 for checkbox in self.main_category_checkboxes.values() if checkbox.isChecked()) > 0
        self.generate_button.setEnabled(has_name and has_main_category)
        
        # Apply button should be disabled until AI content is generated
        self.apply_button.setEnabled(self.ai_content is not None and bool(self.ai_content.strip()))
    
    def _on_main_category_changed(self, state):
        """Handle main category selection changes and enforce 5-selection limit"""
        # Enforce 5-selection limit
        checked_count = sum(1 for checkbox in self.main_category_checkboxes.values() if checkbox.isChecked())
        
        if checked_count > 5:
            # Find and uncheck the checkbox that was just checked
            checkbox = self.sender()
            if checkbox:
                checkbox.setChecked(False)
                checked_count -= 1
            QMessageBox.information(self, "Selection Limit", "You can select a maximum of 5 main categories.")
        
        # Update count label
        self.main_cat_count_label.setText(f"Selected: {checked_count}/5")
        
        # Validate inputs
        self._validate_inputs()
    
    def _generate_game(self):
        """Generate the game content using AI"""
        try:
            # Collect all input data
            game_data = self._collect_game_data()
            
            # Show progress dialog
            progress = QProgressDialog("Generating your game content with AI...", "Cancel", 0, 0, self)
            progress.setWindowTitle("Generating Game Content")
            progress.setWindowModality(Qt.WindowModal)
            progress.setCancelButton(None)
            progress.show()
            fade_widget_in(progress, duration=200)
            
            # Process in background thread to prevent UI freezing
            self._generate_content_async(game_data, progress)
            
        except Exception as e:
            QMessageBox.critical(self, "Generation Error", f"Failed to start game generation: {str(e)}")
    
    def _generate_content_async(self, game_data, progress_dialog):
        """Generate game content in background thread and display in text box"""
        def generate_worker():
            try:
                # Create AI prompt
                ai_prompt = self._create_ai_prompt(game_data)
                
                # Call AI to generate game
                import google.generativeai as genai
                
                # Load config and get proper model (same pattern as other AI features)
                config = load_gamai_config()
                if not config.get('Key'):
                    raise ValueError("AI API key not configured")
                
                # Configure the API
                genai.configure(api_key=config['Key'])
                
                # Get model names from config - use primary model first
                primary_model = config.get('Model', 'gemini-2.5-pro')
                backup_model = config.get('BackupModel', 'gemini-2.5-flash')
                
                # Try primary model first, fallback to backup on error
                try:
                    model = genai.GenerativeModel(primary_model)
                    current_model = primary_model
                except Exception:
                    # If primary model fails (e.g., rate limit), try backup model
                    model = genai.GenerativeModel(backup_model)
                    current_model = backup_model
                
                # Generate response
                response = model.generate_content(ai_prompt)
                
                # Log which model was used
                print(f"Game generation using model: {current_model}")
                
                # Return the full response text for display in text box
                return response.text
                    
            except Exception as e:
                error_msg = str(e)
                print(f"Content generation error: {error_msg}")
                return f"Error: {error_msg}"
        
        # Use QThread for async execution
        class ContentGenerationThread(QThread):
            finished = pyqtSignal(str)
            
            def __init__(self, worker_func):
                super().__init__()
                self.worker_func = worker_func
            
            def run(self):
                result = self.worker_func()
                self.finished.emit(result)
        
        # Store thread as instance variable to prevent garbage collection
        self.generation_thread = ContentGenerationThread(generate_worker)
        self.generation_thread.finished.connect(lambda content: self._on_content_generated(content, progress_dialog))
        self.generation_thread.finished.connect(self._cleanup_thread)
        self.generation_thread.start()
    
    def _on_content_generated(self, content, progress_dialog):
        """Handle content generation completion"""
        # Only proceed if thread still exists and dialog is still active
        if not hasattr(self, 'generation_thread') or self.generation_thread is None:
            return
            
        progress_dialog.close()
        
        # Display content in text box
        self.ai_content = content
        self.ai_content_display.setPlainText(content)
        
        # Enable apply button
        self.apply_button.setEnabled(True)
        
        # Scroll to content area
        self.ai_content_display.setFocus()
        
        QMessageBox.information(
            self,
            "Content Generated!",
            "Game content has been generated and is displayed below.\nReview the content and click 'Apply & Create Game' to finalize your game."
        )
    
    def _apply_game(self):
        """Apply the generated content to create the actual game"""
        try:
            if not self.ai_content or not self.ai_content.strip():
                QMessageBox.warning(self, "No Content", "No AI generated content to apply. Please generate content first.")
                return
            
            # Extract HTML from the generated content
            game_data = self._collect_game_data()
            html_content = self._extract_html_from_response(self.ai_content)
            
            if not html_content:
                QMessageBox.critical(self, "Content Error", "Could not extract valid HTML content from AI response. Please regenerate the content.")
                return
            
            # Create the actual game files
            parent_window = self.parent()
            if not parent_window or not hasattr(parent_window, 'game_service'):
                raise ValueError("Unable to access game service")
            
            # Create the game using the existing method
            success = self._create_generated_game(game_data, html_content, parent_window)
            
            if success:
                self.generated_game_name = game_data["name"]
                
                # Show success message
                QMessageBox.information(
                    parent_window,
                    "Game Created Successfully!",
                    f"Game '{self.generated_game_name}' has been created and added to your collection!"
                )
                
                # Refresh games list and highlight the new game
                updated_games = parent_window.game_service.discover_games()
                parent_window.games = updated_games
                parent_window.game_list.display_games(updated_games)
                
                # Highlight the new game after a brief delay
                QTimer.singleShot(500, lambda: parent_window.game_list.highlight_game(self.generated_game_name))
                
                # Close the dialog
                self.accept()
            else:
                QMessageBox.critical(
                    self,
                    "Creation Failed",
                    "Failed to create the game files. Please try again."
                )
                
        except Exception as e:
            QMessageBox.critical(self, "Apply Error", f"Failed to apply generated content: {str(e)}")
    
    def _collect_game_data(self):
        """Collect and validate all input data"""
        name = self.name_input.text().strip()
        if not name:
            raise ValueError("Game name is required")
        
        # Get selected main categories
        main_categories = []
        for category, checkbox in self.main_category_checkboxes.items():
            if checkbox.isChecked():
                main_categories.append(category)
        
        if not main_categories:
            raise ValueError("Please select at least 1 main category")
        
        # Get selected sub categories
        sub_categories = []
        for category, checkbox in self.sub_category_checkboxes.items():
            if checkbox.isChecked():
                sub_categories.append(category)
        
        prompt = self.prompt_input.toPlainText().strip()
        
        return {
            "name": name,
            "version": "0.0.1",
            "type": self.type_combo.currentText(),
            "players": self.players_combo.currentText(),
            "main_categories": main_categories,
            "sub_categories": sub_categories,
            "prompt": prompt
        }
    
    def _generate_game_async(self, game_data, progress_dialog):
        """Generate game in background thread"""
        def generate_worker():
            try:
                # Get parent window to access game service
                parent_window = self.parent()
                if not parent_window or not hasattr(parent_window, 'game_service'):
                    raise ValueError("Unable to access game service")
                
                # Create AI prompt
                ai_prompt = self._create_ai_prompt(game_data)
                
                # Call AI to generate game
                import google.generativeai as genai
                
                # Load config and get proper model (same pattern as other AI features)
                config = load_gamai_config()
                if not config.get('Key'):
                    raise ValueError("AI API key not configured")
                
                # Configure the API
                genai.configure(api_key=config['Key'])
                
                # Get model names from config - use primary model first
                primary_model = config.get('Model', 'gemini-2.5-pro')
                backup_model = config.get('BackupModel', 'gemini-2.5-flash')
                
                # Try primary model first, fallback to backup on error
                try:
                    model = genai.GenerativeModel(primary_model)
                    current_model = primary_model
                except Exception:
                    # If primary model fails (e.g., rate limit), try backup model
                    model = genai.GenerativeModel(backup_model)
                    current_model = backup_model
                
                # Generate response
                response = model.generate_content(ai_prompt)
                
                # Log which model was used
                print(f"Game generation using model: {current_model}")
                
                # Extract HTML content
                html_content = self._extract_html_from_response(response.text)
                
                if not html_content:
                    raise ValueError("AI did not generate valid HTML content")
                
                # Create the game
                success = self._create_generated_game(game_data, html_content, parent_window)
                
                if success:
                    self.generated_game_name = game_data["name"]
                    return True
                else:
                    return False
                    
            except Exception as e:
                error_msg = str(e)
                print(f"Game generation error: {error_msg}")
                
                # Provide more helpful error messages
                if "not found" in error_msg.lower() or "not supported" in error_msg.lower():
                    print("Model configuration issue - check AI model settings")
                elif "API key" in error_msg.lower() or "authentication" in error_msg.lower():
                    print("API key issue - check AI configuration")
                elif "quota" in error_msg.lower() or "rate limit" in error_msg.lower():
                    print("Rate limit reached - try again later or check API quota")
                
                return False
        
        # Use QThread for async execution
        class GenerationThread(QThread):
            finished = pyqtSignal(bool)
            
            def __init__(self, worker_func):
                super().__init__()
                self.worker_func = worker_func
            
            def run(self):
                result = self.worker_func()
                self.finished.emit(result)
        
        # Store thread as instance variable to prevent garbage collection
        self.generation_thread = GenerationThread(generate_worker)
        self.generation_thread.finished.connect(lambda success: self._on_generation_finished(success, progress_dialog))
        self.generation_thread.finished.connect(self._cleanup_thread)
        self.generation_thread.start()
    
    def _cleanup_thread(self):
        """Clean up thread after completion"""
        if hasattr(self, 'generation_thread') and self.generation_thread is not None:
            self.generation_thread = None
    
    def _create_ai_prompt(self, game_data):
        """Create comprehensive AI prompt for game generation"""
        prompt = f"""
You are an expert game developer. Create a complete, playable HTML5 game based on these specifications:

**GAME SPECIFICATIONS:**
- Name: {game_data['name']}
- Version: {game_data['version']}
- Type: {game_data['type']} Game
- Players: {game_data['players']} player(s)
- Main Categories: {', '.join(game_data['main_categories']) if game_data['main_categories'] else 'None specified'}
- Sub Categories: {', '.join(game_data['sub_categories']) if game_data['sub_categories'] else 'None specified'}
- Custom Instructions: {game_data['prompt'] if game_data['prompt'] else 'None provided'}

**TECHNICAL REQUIREMENTS:**
1. Use HTML5 + CSS3 + JavaScript (HTML+CSS+JS) for complete implementation
2. Generate a COMPLETE, FULL-FEATURED game (not a prototype or demo)
3. Include comprehensive gameplay mechanics, levels, challenges, and objectives
4. Implement professional VFX, animations, and visual effects using CSS3/JavaScript
5. Add engaging SFX (sound effects) and background music using Web Audio API
6. Create intuitive controls and responsive gameplay
7. Implement proper game states (start screen, gameplay, game over, victory)
8. Use modern CSS3 animations, transitions, and visual effects
9. Make it visually appealing with modern styling and animations
10. Ensure cross-browser compatibility
11. Include proper game progression, scoring, and win/lose conditions
12. All code should be self-contained in a single HTML file

**OUTPUT FORMAT:**
Return ONLY the complete HTML code wrapped in triple backticks with 'html' language specifier:
```html
[Your complete HTML5 game code here - include all HTML, CSS, and JavaScript in one file]
```

**GAME CONTENT GUIDELINES:**
- If custom instructions mention specific features (like "10 levels", "boss battles"), implement them fully
- Create engaging gameplay that matches the specified categories
- Ensure the game is immediately playable and enjoyable
- Add polished visual effects using CSS3 animations and JavaScript
- Include immersive audio elements
- Use modern web technologies (HTML5 Canvas, Web Audio API, CSS3 features)

Generate a complete, production-ready HTML5 game using HTML+CSS+JavaScript now!
"""
        return prompt
    
    def _extract_html_from_response(self, response_text):
        """Extract HTML content from AI response"""
        try:
            # Look for HTML code block
            if "```html" in response_text:
                start = response_text.find("```html") + 7
                end = response_text.find("```", start)
                if end != -1:
                    return response_text[start:end].strip()
            
            # Fallback: look for any code block
            if "```" in response_text:
                start = response_text.find("```") + 3
                end = response_text.rfind("```")
                if end > start:
                    return response_text[start:end].strip()
            
            # If no code block found, try to extract HTML-like content
            if "<html" in response_text.lower() or "<!doctype" in response_text.lower():
                return response_text.strip()
            
            return None
        except Exception as e:
            print(f"Error extracting HTML: {e}")
            return None
    
    def _create_generated_game(self, game_data, html_content, parent_window):
        """Create the actual game files"""
        try:
            # Use the game service to create the game
            new_game = parent_window.game_service.create_game(
                name=game_data["name"],
                version=game_data["version"],
                game_type=game_data["type"],
                players=game_data["players"],
                main_categories=game_data["main_categories"],
                sub_categories=game_data["sub_categories"]
            )
            
            if not new_game:
                return False
            
            # Write the generated HTML content to index.html
            with open(new_game.html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Refresh the games list
            updated_games = parent_window.game_service.discover_games()
            parent_window.games = updated_games
            parent_window.game_list.display_games(updated_games)
            
            # Highlight the new game
            QTimer.singleShot(500, lambda: parent_window.game_list.highlight_game(new_game.name))
            
            return True
            
        except Exception as e:
            print(f"Error creating generated game: {e}")
            return False
    
    def _on_generation_finished(self, success, progress_dialog):
        """Handle generation completion"""
        # Only proceed if thread still exists and dialog is still active
        if not hasattr(self, 'generation_thread') or self.generation_thread is None:
            return
            
        progress_dialog.close()
        
        if success:
            QMessageBox.information(
                self.parent(),
                "Game Generated Successfully!",
                f"Game '{self.generated_game_name}' has been created and added to your collection!"
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Generation Failed",
                "Failed to generate the game. Please check your inputs and try again."
            )
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=300)
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=250, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=250, hide_after=True)
        super().reject()


class SurpriseGameDialog(QDialog):
    """Dialog for creating surprise games with AI-powered randomization"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎲 Surprise AI Game Creation")
        self.setFixedSize(800, 800)
        self.setModal(True)
        self.generated_game_name = None
        self.generation_thread = None
        self.ai_content = None
        self.randomized_data = None  # Store randomized game data
        self.generated_game_name = None  # Store the actual created game name
        self._setup_ui()
    
    def closeEvent(self, event):
        """Handle dialog close - clean up thread if running"""
        if hasattr(self, 'generation_thread') and self.generation_thread is not None:
            if self.generation_thread.isRunning():
                self.generation_thread.quit()
                self.generation_thread.wait()
                self.generation_thread = None
        event.accept()
    
    def _setup_ui(self):
        # Main scrollable layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Content widget for scrolling
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("🎲 Create Surprise Game with AI")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 20px; color: #CCCCCC;")
        layout.addWidget(title_label)
        
        # Randomization Section
        randomization_group = QGroupBox("🎯 Random Game Parameters")
        randomization_layout = QVBoxLayout(randomization_group)
        
        # ROLL Button
        roll_layout = QHBoxLayout()
        self.roll_button = QPushButton("🎰 ROLL THE DICE!")
        self.roll_button.setFixedSize(200, 60)
        self.roll_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
        """)
        self.roll_button.clicked.connect(self._roll_randomization)
        roll_layout.addStretch()
        roll_layout.addWidget(self.roll_button)
        roll_layout.addStretch()
        randomization_layout.addLayout(roll_layout)
        
        # Randomized Display Area
        self.randomized_display = QTextEdit()
        self.randomized_display.setReadOnly(True)
        self.randomized_display.setMaximumHeight(150)
        self.randomized_display.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                padding: 10px;
                font-size: 14px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        self.randomized_display.setPlaceholderText("🎯 Roll the dice to see your randomized game parameters!\n\nClick 'ROLL THE DICE!' to generate random game settings.")
        randomization_layout.addWidget(self.randomized_display)
        
        # Apply Roll Button
        apply_roll_layout = QHBoxLayout()
        self.apply_roll_button = QPushButton("✅ Apply ROLL")
        self.apply_roll_button.setFixedSize(150, 40)
        self.apply_roll_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.apply_roll_button.clicked.connect(self._apply_roll)
        self.apply_roll_button.setEnabled(False)
        apply_roll_layout.addStretch()
        apply_roll_layout.addWidget(self.apply_roll_button)
        apply_roll_layout.addStretch()
        randomization_layout.addLayout(apply_roll_layout)
        
        layout.addWidget(randomization_group)
        
        # AI Content Display Area
        content_group = QGroupBox("🤖 AI Generated Surprise Content")
        content_layout = QVBoxLayout(content_group)
        
        self.ai_content_display = QTextEdit()
        self.ai_content_display.setReadOnly(True)
        self.ai_content_display.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)
        self.ai_content_display.setPlaceholderText("🎯 Randomized game content will appear here...\n\nStep 1: Click 'ROLL THE DICE!' to randomize parameters\nStep 2: Click 'Apply ROLL' to set parameters\nStep 3: Review the AI content below\nStep 4: Click 'Apply Surprise' to create your game")
        content_layout.addWidget(self.ai_content_display)
        
        layout.addWidget(content_group)
        
        # Button Section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)
        
        # Generate Button
        self.generate_button = QPushButton("🎮 Generate Surprise")
        self.generate_button.setFixedSize(200, 50)
        self.generate_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
            }
        """)
        self.generate_button.clicked.connect(self._generate_surprise)
        button_layout.addWidget(self.generate_button)
        
        # Apply Button
        self.apply_button = QPushButton("✅ Apply Surprise")
        self.apply_button.setFixedSize(200, 50)
        self.apply_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background-color: #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
            }
        """)
        self.apply_button.clicked.connect(self._apply_surprise)
        self.apply_button.setEnabled(False)
        button_layout.addWidget(self.apply_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Add scroll widget to scroll area
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
    
    def _roll_randomization(self):
        """Generate random game parameters"""
        # Random main categories (1-5)
        main_cats = [
            "action", "adventure", "arcade", "puzzle", "racing", 
            "sports", "strategy", "shooter", "rpg", "simulation"
        ]
        num_main = random.randint(1, 5)
        randomized_main_cats = random.sample(main_cats, num_main)
        
        # Random type
        game_type = random.choice(["2D", "3D"])
        
        # Random players
        players = random.choice(["1", "2"])
        
        # Random sub-categories (0-20)
        sub_cats = [
            "fast-paced", "story-driven", "competitive", "cooperative",
            "casual", "hardcore", "retro", "modern", "pixel-art",
            "realistic", "cartoon", "horror", "comedy", "sci-fi",
            "fantasy", "mythology", "historical", "contemporary",
            "abstract", "minimalist", "detailed", "open-world",
            "linear", "procedural", "hand-drawn", "3d-rendered",
            "top-down", "side-scrolling", "first-person", "third-person"
        ]
        num_sub = random.randint(0, 20)
        randomized_sub_cats = random.sample(sub_cats, min(num_sub, len(sub_cats)))
        
        # Random surprise styles (1-3)
        surprise_styles = [
            "dream core", "nightmare", "heavenly", "devilish", "cocktail",
            "remix", "dark fantasy", "shatters", "souls", "unhinged",
            "ethereal", "abyss", "lucid", "chaotic", "whisper",
            "void", "ephemeral", "twisted", "mirage", "seraphic",
            "frenzy", "gothic", "celestial", "glitch", "phantom",
            "maelstrom", "wraith", "vexing", "macabre", "fusion"
        ]
        num_styles = random.randint(1, 3)
        randomized_styles = random.sample(surprise_styles, num_styles)
        
        # Store randomized data
        self.randomized_data = {
            "main_categories": randomized_main_cats,
            "type": game_type,
            "players": players,
            "sub_categories": randomized_sub_cats,
            "surprise_styles": randomized_styles
        }
        
        # Display randomized info
        display_text = f"🎯 Randomized Game Parameters:\n\n"
        display_text += f"🎮 Type: {game_type}\n"
        display_text += f"👥 Players: {players}\n"
        display_text += f"🏷️ Main Categories: {', '.join(randomized_main_cats)}\n"
        display_text += f"🏷️ Sub Categories: {', '.join(randomized_sub_cats) if randomized_sub_cats else 'None'}\n"
        display_text += f"✨ Surprise Styles: {', '.join(randomized_styles)}\n"
        
        self.randomized_display.setText(display_text)
        self.apply_roll_button.setEnabled(True)
        
        # Reset AI content
        self.ai_content = None
        self.ai_content_display.clear()
        self.apply_button.setEnabled(False)
    
    def _apply_roll(self):
        """Apply the randomized parameters"""
        if not self.randomized_data:
            QMessageBox.warning(self, "No Roll", "Please roll the dice first to generate random parameters.")
            return
        
        # Enable generate button and show user feedback
        self.generate_button.setEnabled(True)
        self.apply_roll_button.setEnabled(False)
        
        QMessageBox.information(
            self,
            "Parameters Applied!",
            f"🎯 Random parameters applied!\n\nYour surprise game will have:\n• Type: {self.randomized_data['type']}\n• Players: {self.randomized_data['players']}\n• Main Categories: {', '.join(self.randomized_data['main_categories'])}\n\nClick 'Generate Surprise' to create your game!"
        )
    
    def _generate_surprise(self):
        """Generate surprise game content using AI"""
        if not self.randomized_data:
            QMessageBox.warning(self, "No Parameters", "Please roll and apply parameters first.")
            return
        
        try:
            # Validate API configuration
            if not is_gamai_configured():
                QMessageBox.warning(self, "API Key Required", "AI generation requires a Gemini API key. Please configure it first.")
                return
            
            # Disable buttons during generation
            self.generate_button.setEnabled(False)
            self.apply_roll_button.setEnabled(False)
            self.apply_button.setEnabled(False)
            
            # Show progress dialog
            progress_dialog = QProgressDialog("Generating surprise game content...", "Cancel", 0, 0, self)
            progress_dialog.setWindowTitle("AI Generation")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.show()
            fade_widget_in(progress_dialog, duration=200)
            
            # Collect game data
            game_data = self._collect_game_data()
            
            # Generate content in thread
            self._generate_content_async(game_data, progress_dialog)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start generation: {str(e)}")
            self._reset_generation_ui()
    
    def _generate_content_async(self, game_data, progress_dialog):
        """Generate content asynchronously - using the SAME pattern as OneShotGameDialog"""
        def generate_worker():
            try:
                # Create AI prompt
                ai_prompt = self._create_surprise_prompt(game_data)
                
                # Call AI to generate game
                import google.generativeai as genai
                
                # Load config and get proper model (same pattern as other AI features)
                config = load_gamai_config()
                if not config.get('Key'):
                    raise ValueError("AI API key not configured")
                
                # Configure the API
                genai.configure(api_key=config['Key'])
                
                # Get model names from config - use primary model first
                primary_model = config.get('Model', 'gemini-2.5-pro')
                backup_model = config.get('BackupModel', 'gemini-2.5-flash')
                
                # Try primary model first, fallback to backup on error
                try:
                    model = genai.GenerativeModel(primary_model)
                    current_model = primary_model
                except Exception:
                    # If primary model fails (e.g., rate limit), try backup model
                    model = genai.GenerativeModel(backup_model)
                    current_model = backup_model
                
                # Generate response
                response = model.generate_content(ai_prompt)
                
                # Log which model was used
                print(f"Surprise game generation using model: {current_model}")
                
                # Return the full response text for display in text box
                return response.text
                    
            except Exception as e:
                error_msg = str(e)
                print(f"Content generation error: {error_msg}")
                return f"Error: {error_msg}"
        
        # Use QThread for async execution - EXACTLY like OneShotGameDialog
        class ContentGenerationThread(QThread):
            finished = pyqtSignal(str)
            
            def __init__(self, worker_func):
                super().__init__()
                self.worker_func = worker_func
            
            def run(self):
                result = self.worker_func()
                self.finished.emit(result)
        
        # Store thread as instance variable to prevent garbage collection
        self.generation_thread = ContentGenerationThread(generate_worker)
        self.generation_thread.finished.connect(lambda content: self._on_content_generated(content, progress_dialog))
        self.generation_thread.finished.connect(self._cleanup_thread)
        self.generation_thread.start()
    
    def _cleanup_thread(self):
        """Clean up thread after completion"""
        if hasattr(self, 'generation_thread') and self.generation_thread is not None:
            self.generation_thread = None
    
    def _on_content_generated(self, content, progress_dialog):
        """Handle content generation completion"""
        # Only proceed if thread still exists and dialog is still active
        if not hasattr(self, 'generation_thread') or self.generation_thread is None:
            return
            
        progress_dialog.close()
        
        # Display content in text box - use the SAME method as OneShotGameDialog
        self.ai_content = content
        self.ai_content_display.setPlainText(content)
        
        # Enable apply button
        self.apply_button.setEnabled(True)
        
        # Scroll to content area
        self.ai_content_display.setFocus()
        
        QMessageBox.information(
            self,
            "Content Generated!",
            "🎯 Surprise game content generated successfully!\n\nReview the content and click 'Apply Surprise' to create your game."
        )
        
        self._reset_generation_ui()
    
    def _reset_generation_ui(self):
        """Reset generation UI state"""
        self.generate_button.setEnabled(True)
        if self.randomized_data:
            self.apply_roll_button.setEnabled(True)
    
    def _create_surprise_prompt(self, game_data):
        """Create AI prompt for surprise game generation"""
        main_cats = ', '.join(game_data['main_categories'])
        sub_cats = ', '.join(game_data['sub_categories']) if game_data['sub_categories'] else 'None'
        styles = ', '.join(game_data['surprise_styles'])
        
        prompt = f"""🎲 SURPRISE GAME CREATION CHALLENGE 🎲

You are tasked with creating a unique and surprising HTML5 game that embodies the following randomized parameters:

🎯 GAME PARAMETERS:
• Type: {game_data['type']}
• Players: {game_data['players']} player(s)
• Main Categories: {main_cats}
• Sub Categories: {sub_cats}
• Surprise Styles: {styles}

🎨 CREATIVE CHALLENGE:
The game must incorporate the surprise style(s) '{styles}' as its core aesthetic and gameplay theme. These styles should influence:
- Visual design (colors, effects, atmosphere)
- Gameplay mechanics and rules
- Sound design concepts (describe in code comments)
- User interface and experience
- Overall game feel and emotion

🎮 GAME REQUIREMENTS:
1. Create a complete, playable HTML5 game
2. Include HTML, CSS, and JavaScript in a single file
3. Make it genuinely surprising and unique - use the randomized elements creatively
4. Ensure proper game loop with win/lose conditions
5. Include responsive design that works on different screen sizes
6. Add engaging visual effects that match the surprise styles
7. Include clear game instructions and feedback

🎯 SPECIAL INSTRUCTIONS:
- The name is ALWAYS "Surprise" (with auto-numbering for duplicates)
- Version is always "0.0.0"
- Make each game a fresh surprise - no repetition of common game types
- Use the surprise styles to create unexpected gameplay twists
- Focus on originality and creativity over complexity

Please generate the complete HTML5 game code wrapped in a code block:

```html
[Your complete HTML5 game code here]
```

Remember: This should be a genuinely surprising and delightful gaming experience! 🎲✨"""
        return prompt
    
    def _apply_surprise(self):
        """Apply the surprise game creation"""
        if not self.ai_content:
            QMessageBox.warning(self, "No Content", "No AI generated content to apply. Please generate content first.")
            return
        
        if not self.randomized_data:
            QMessageBox.warning(self, "No Parameters", "No randomized parameters found. Please roll the dice first.")
            return
        
        # Extract HTML from the generated content
        game_data = self._collect_game_data()
        html_content = self._extract_html_from_response(self.ai_content)
        
        if not html_content:
            QMessageBox.critical(self, "Content Error", "Could not extract valid HTML content from AI response. Please regenerate the content.")
            return
        
        # Create the actual game files
        parent_window = self.parent()
        if not parent_window or not hasattr(parent_window, 'game_service'):
            QMessageBox.critical(self, "Error", "Unable to access game service")
            return
        
        # Create the game using the existing method
        new_game = self._create_generated_game(game_data, html_content, parent_window)
        
        if new_game:
            self.generated_game_name = new_game.name  # Use the actual name returned by create_game
            
            # Show success message
            QMessageBox.information(
                parent_window,
                "Surprise Game Created Successfully!",
                f"🎲 Surprise game '{self.generated_game_name}' has been created and added to your collection!\n\nThe game incorporates the randomized elements and surprise styles for a unique experience!"
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Creation Failed",
                "Failed to create the surprise game. Please try again."
            )
    
    def _collect_game_data(self):
        """Collect game data from randomized parameters"""
        if not self.randomized_data:
            raise ValueError("No randomized game data available")
        
        return {
            "name": "Surprise",
            "version": "0.0.0",
            "type": self.randomized_data["type"],
            "players": self.randomized_data["players"],
            "main_categories": self.randomized_data["main_categories"],
            "sub_categories": self.randomized_data["sub_categories"],
            "surprise_styles": self.randomized_data["surprise_styles"]
        }
    
    def _extract_html_from_response(self, response_text):
        """Extract HTML content from AI response"""
        try:
            # Look for HTML code blocks
            import re
            html_pattern = r'```html\s*\n(.*?)\n```'
            matches = re.findall(html_pattern, response_text, re.DOTALL)
            
            if matches:
                html_content = matches[0].strip()
                # Basic validation
                if html_content.lower().startswith('<!doctype') or '<html' in html_content.lower():
                    return html_content
            
            # Fallback: look for any code blocks
            code_pattern = r'```\s*\n(.*?)\n```'
            matches = re.findall(code_pattern, response_text, re.DOTALL)
            
            if matches:
                content = matches[0].strip()
                # Check if it looks like HTML
                if any(tag in content.lower() for tag in ['<html', '<head', '<body', '<canvas', '<div', '<script']):
                    return content
            
            return None
            
        except Exception as e:
            print(f"Error extracting HTML: {e}")
            return None
    
    def _create_generated_game(self, game_data, html_content, parent_window):
        """Create the actual game files - using the same pattern as OneShotGameDialog"""
        try:
            # Use the game service to create the game
            new_game = parent_window.game_service.create_game(
                name=game_data["name"],
                version=game_data["version"],
                game_type=game_data["type"],
                players=game_data["players"],
                main_categories=game_data["main_categories"],
                sub_categories=game_data["sub_categories"]
            )
            
            if not new_game:
                return False
            
            # Write the generated HTML content to index.html
            with open(new_game.html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Refresh the games list - using the SAME pattern as OneShotGameDialog
            updated_games = parent_window.game_service.discover_games()
            parent_window.games = updated_games
            parent_window.game_list.display_games(updated_games)
            
            # Highlight the new game
            QTimer.singleShot(500, lambda: parent_window.game_list.highlight_game(new_game.name))
            
            return new_game
            
        except Exception as e:
            print(f"Error creating surprise game: {e}")
            return None
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=300)
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=250, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=250, hide_after=True)
        super().reject()


class ForYouGameDialog(QDialog):
    """Dialog for creating personalized games based on user's game collection"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 For You AI Game Creation")
        self.setFixedSize(800, 800)
        self.setModal(True)
        self.generated_game_name = None
        self.generation_thread = None
        self.ai_content = None
        self.randomized_data = None  # Store randomized game data
        self.selected_manifests = []  # Store selected game manifests for inspiration
        self.generated_game_name = None  # Store the actual created game name
        self.available_games = []  # Will be populated from parent window
        self._setup_ui()
        self._load_available_games()
    
    def closeEvent(self, event):
        """Handle dialog close - clean up thread if running"""
        if hasattr(self, 'generation_thread') and self.generation_thread is not None:
            if self.generation_thread.isRunning():
                self.generation_thread.quit()
                self.generation_thread.wait()
                self.generation_thread = None
        event.accept()
    
    def _setup_ui(self):
        # Main scrollable layout
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Content widget for scrolling
        scroll_widget = QWidget()
        layout = QVBoxLayout(scroll_widget)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("🎯 Create Personalized Game with AI")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; margin-bottom: 20px; color: #CCCCCC;")
        layout.addWidget(title_label)
        
        # Manifests Section
        manifests_group = QGroupBox("📋 Choose Your Inspiration Games")
        manifests_layout = QVBoxLayout(manifests_group)
        
        # Auto/Manual selection
        selection_buttons_layout = QHBoxLayout()
        
        # Auto Button
        self.auto_button = QPushButton("🎲 Auto Select (1-5 games)")
        self.auto_button.setFixedSize(200, 50)
        self.auto_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.auto_button.clicked.connect(self._auto_select_manifests)
        selection_buttons_layout.addWidget(self.auto_button)
        
        # Manual Button
        self.manual_button = QPushButton("🎯 Manual Select")
        self.manual_button.setFixedSize(200, 50)
        self.manual_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.manual_button.clicked.connect(self._manual_select_manifests)
        selection_buttons_layout.addWidget(self.manual_button)
        
        selection_buttons_layout.addStretch()
        manifests_layout.addLayout(selection_buttons_layout)
        
        # Selected manifests display
        self.manifests_display = QTextEdit()
        self.manifests_display.setReadOnly(True)
        self.manifests_display.setMaximumHeight(120)
        self.manifests_display.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                padding: 10px;
                font-size: 13px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        self.manifests_display.setPlaceholderText("📋 Selected games for inspiration will appear here...\n\nChoose 'Auto Select' for random games or 'Manual Select' to choose your own!")
        manifests_layout.addWidget(self.manifests_display)
        
        layout.addWidget(manifests_group)
        
        # Randomization Section (like surprise but without surprise styles)
        randomization_group = QGroupBox("🎯 Random Game Parameters")
        randomization_layout = QVBoxLayout(randomization_group)
        
        # ROLL Button
        roll_layout = QHBoxLayout()
        self.roll_button = QPushButton("🎰 ROLL THE DICE!")
        self.roll_button.setFixedSize(200, 60)
        self.roll_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.roll_button.clicked.connect(self._roll_randomization)
        roll_layout.addStretch()
        roll_layout.addWidget(self.roll_button)
        roll_layout.addStretch()
        randomization_layout.addLayout(roll_layout)
        
        # Randomized Display Area
        self.randomized_display = QTextEdit()
        self.randomized_display.setReadOnly(True)
        self.randomized_display.setMaximumHeight(150)
        self.randomized_display.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                padding: 10px;
                font-size: 14px;
                font-family: 'Consolas', 'Monaco', monospace;
            }
        """)
        self.randomized_display.setPlaceholderText("🎯 Roll the dice to see your randomized game parameters!\n\nClick 'ROLL THE DICE!' to generate random game settings.")
        randomization_layout.addWidget(self.randomized_display)
        
        # Apply Roll Button
        apply_roll_layout = QHBoxLayout()
        self.apply_roll_button = QPushButton("✅ Apply ROLL")
        self.apply_roll_button.setFixedSize(150, 40)
        self.apply_roll_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.apply_roll_button.clicked.connect(self._apply_roll)
        self.apply_roll_button.setEnabled(False)
        apply_roll_layout.addStretch()
        apply_roll_layout.addWidget(self.apply_roll_button)
        apply_roll_layout.addStretch()
        randomization_layout.addLayout(apply_roll_layout)
        
        layout.addWidget(randomization_group)
        
        # AI Content Display Area
        content_group = QGroupBox("🤖 AI Generated For You Content")
        content_layout = QVBoxLayout(content_group)
        
        self.ai_content_display = QTextEdit()
        self.ai_content_display.setReadOnly(True)
        self.ai_content_display.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)
        self.ai_content_display.setPlaceholderText("🎯 Personalized game content will appear here...\n\nStep 1: Select inspiration games (Auto or Manual)\nStep 2: Click 'ROLL THE DICE!' to randomize parameters\nStep 3: Click 'Apply ROLL' to set parameters\nStep 4: Review the AI content below\nStep 5: Click 'Apply For You' to create your game")
        content_layout.addWidget(self.ai_content_display)
        
        layout.addWidget(content_group)
        
        # Button Section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)
        
        # Generate Button
        self.generate_button = QPushButton("🎮 Generate For You")
        self.generate_button.setFixedSize(200, 50)
        self.generate_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.generate_button.clicked.connect(self._generate_foryou)
        button_layout.addWidget(self.generate_button)
        
        # Apply Button
        self.apply_button = QPushButton("✅ Apply For You")
        self.apply_button.setFixedSize(200, 50)
        self.apply_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background-color: #E5E5E5;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
            }
        """)
        self.apply_button.clicked.connect(self._apply_foryou)
        self.apply_button.setEnabled(False)
        button_layout.addWidget(self.apply_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Add scroll widget to scroll area
        scroll_area.setWidget(scroll_widget)
        main_layout.addWidget(scroll_area)
    
    def _load_available_games(self):
        """Load available games from parent window with full manifests"""
        parent = self.parent()
        if parent and hasattr(parent, 'game_service'):
            # Load fresh games with full manifests from the service
            self.available_games = parent.game_service.discover_games()
            print(f"Loaded {len(self.available_games)} games with full manifests for For You feature")
        elif parent and hasattr(parent, 'games'):
            # Fallback to parent's games list
            self.available_games = parent.games
        else:
            self.available_games = []
    
    def _auto_select_manifests(self):
        """Automatically select 1-5 random games from the collection"""
        if not self.available_games:
            QMessageBox.information(self, "No Games", "No games available for selection.")
            return
        
        # Select 1-5 random games
        num_games = random.randint(1, min(5, len(self.available_games)))
        self.selected_manifests = random.sample(self.available_games, num_games)
        
        # Display selected games with COMPLETE manifest details
        display_text = f"🎯 Auto-selected {num_games} games for inspiration:\n\n"
        for i, game in enumerate(self.selected_manifests, 1):
            # Get detailed game information
            game_name = getattr(game, 'name', 'Unknown Game')
            game_version = getattr(game, 'version', 'Unknown')
            game_type = getattr(game, 'type', 'Unknown')
            game_players = getattr(game, 'players', 'Unknown')
            main_categories = getattr(game, 'main_categories', [])
            sub_categories = getattr(game, 'sub_categories', [])
            played_times = getattr(game, 'played_times', 0)
            edits = getattr(game, 'edits', 0)
            created_date = getattr(game, 'created', 'Unknown')
            time_played = getattr(game, 'time_played', {})
            
            # Handle rating and feedback with proper null handling
            rating = getattr(game, 'rating', None)
            feedback = getattr(game, 'feedback', None)
            
            # Convert to display values - use "null" for empty/None values
            if rating is None or rating == [] or rating == '':
                rating_display = 'null'
            else:
                rating_display = str(rating)
                
            if feedback is None or feedback == [] or feedback == '':
                feedback_display = 'null'
            else:
                feedback_display = str(feedback)
            
            # Format categories
            categories_str = ', '.join([cat for cat in main_categories if cat != 'null']) if main_categories else 'Unknown'
            subcats_str = ', '.join([cat for cat in sub_categories if cat != 'null']) if sub_categories else 'Unknown'
            
            # Format time played - ONLY minutes as requested
            time_minutes = 0
            if time_played and isinstance(time_played, dict):
                time_minutes = time_played.get('minutes', 0)
            
            # Format creation date
            if created_date != 'Unknown' and created_date:
                created_formatted = created_date[:10] if len(created_date) >= 10 else created_date
            else:
                created_formatted = 'Unknown'
            
            display_text += f"{i}. {game_name} (v{game_version})\n"
            display_text += f"   🎮 Type: {game_type} | 👥 Players: {game_players}\n"
            display_text += f"   🏷️ Categories: {categories_str}\n"
            display_text += f"   🏷️ Sub-Categories: {subcats_str}\n"
            display_text += f"   ⏱️ Time: {time_minutes} min | 📊 Plays: {played_times} | ✏️ Edits: {edits}\n"
            display_text += f"   ⭐ Rating: {rating_display} | 💬 Feedback: {feedback_display}\n"
            display_text += f"   📅 Created: {created_formatted}\n\n"
        
        self.manifests_display.setText(display_text)
        
        # Enable roll button if not already enabled
        if not self.apply_roll_button.isEnabled():
            self.roll_button.setEnabled(True)
        
        QMessageBox.information(
            self,
            "Games Selected!",
            f"🎯 {num_games} games have been automatically selected as inspiration!\n\nThese games will guide the AI to create a personalized experience that matches your taste."
        )
    
    def _manual_select_manifests(self):
        """Manually select games from the available collection"""
        if not self.available_games:
            QMessageBox.information(self, "No Games", "No games available for selection.")
            return
        
        # Create manual selection dialog
        dialog = ForYouGameSelectionDialog(self.available_games, self)
        if dialog.exec_() == QDialog.Accepted:
            selected_games = dialog.get_selected_games()
            if selected_games:
                self.selected_manifests = selected_games
                
                # Display selected games with COMPLETE manifest details
                display_text = f"🎯 Manually selected {len(selected_games)} games for inspiration:\n\n"
                for i, game in enumerate(selected_games, 1):
                    # Get detailed game information
                    game_name = getattr(game, 'name', 'Unknown Game')
                    game_version = getattr(game, 'version', 'Unknown')
                    game_type = getattr(game, 'type', 'Unknown')
                    game_players = getattr(game, 'players', 'Unknown')
                    main_categories = getattr(game, 'main_categories', [])
                    sub_categories = getattr(game, 'sub_categories', [])
                    played_times = getattr(game, 'played_times', 0)
                    edits = getattr(game, 'edits', 0)
                    created_date = getattr(game, 'created', 'Unknown')
                    time_played = getattr(game, 'time_played', {})
                    
                    # Handle rating and feedback with proper null handling
                    rating = getattr(game, 'rating', None)
                    feedback = getattr(game, 'feedback', None)
                    
                    # Convert to display values - use "null" for empty/None values
                    if rating is None or rating == [] or rating == '':
                        rating_display = 'null'
                    else:
                        rating_display = str(rating)
                        
                    if feedback is None or feedback == [] or feedback == '':
                        feedback_display = 'null'
                    else:
                        feedback_display = str(feedback)
                    
                    # Format categories
                    categories_str = ', '.join([cat for cat in main_categories if cat != 'null']) if main_categories else 'Unknown'
                    subcats_str = ', '.join([cat for cat in sub_categories if cat != 'null']) if sub_categories else 'Unknown'
                    
                    # Format time played - ONLY minutes as requested
                    time_minutes = 0
                    if time_played and isinstance(time_played, dict):
                        time_minutes = time_played.get('minutes', 0)
                    
                    # Format creation date
                    if created_date != 'Unknown' and created_date:
                        created_formatted = created_date[:10] if len(created_date) >= 10 else created_date
                    else:
                        created_formatted = 'Unknown'
                    
                    display_text += f"{i}. {game_name} (v{game_version})\n"
                    display_text += f"   🎮 Type: {game_type} | 👥 Players: {game_players}\n"
                    display_text += f"   🏷️ Categories: {categories_str}\n"
                    display_text += f"   🏷️ Sub-Categories: {subcats_str}\n"
                    display_text += f"   ⏱️ Time: {time_minutes} min | 📊 Plays: {played_times} | ✏️ Edits: {edits}\n"
                    display_text += f"   ⭐ Rating: {rating_display} | 💬 Feedback: {feedback_display}\n"
                    display_text += f"   📅 Created: {created_formatted}\n\n"
                
                self.manifests_display.setText(display_text)
                
                # Enable roll button if not already enabled
                if not self.apply_roll_button.isEnabled():
                    self.roll_button.setEnabled(True)
                
                QMessageBox.information(
                    self,
                    "Games Selected!",
                    f"🎯 {len(selected_games)} games have been manually selected as inspiration!\n\nThese games will guide the AI to create a personalized experience."
                )
    
    def _roll_randomization(self):
        """Generate random game parameters (same as surprise but without surprise styles)"""
        # Random main categories (1-5)
        main_cats = [
            "action", "adventure", "arcade", "puzzle", "racing", 
            "sports", "strategy", "shooter", "rpg", "simulation"
        ]
        num_main = random.randint(1, 5)
        randomized_main_cats = random.sample(main_cats, num_main)
        
        # Random type
        game_type = random.choice(["2D", "3D"])
        
        # Random players
        players = random.choice(["1", "2"])
        
        # Random sub-categories (0-20)
        sub_cats = [
            "fast-paced", "story-driven", "competitive", "cooperative",
            "casual", "hardcore", "retro", "modern", "pixel-art",
            "realistic", "cartoon", "horror", "comedy", "sci-fi",
            "fantasy", "mythology", "historical", "contemporary",
            "abstract", "minimalist", "detailed", "open-world",
            "linear", "procedural", "hand-drawn", "3d-rendered",
            "top-down", "side-scrolling", "first-person", "third-person"
        ]
        num_sub = random.randint(0, 20)
        randomized_sub_cats = random.sample(sub_cats, min(num_sub, len(sub_cats)))
        
        # Store randomized data (NO surprise styles for For You)
        self.randomized_data = {
            "main_categories": randomized_main_cats,
            "type": game_type,
            "players": players,
            "sub_categories": randomized_sub_cats
        }
        
        # Display randomized info
        display_text = f"🎯 Randomized Game Parameters:\n\n"
        display_text += f"🎮 Type: {game_type}\n"
        display_text += f"👥 Players: {players}\n"
        display_text += f"🏷️ Main Categories: {', '.join(randomized_main_cats)}\n"
        display_text += f"🏷️ Sub Categories: {', '.join(randomized_sub_cats) if randomized_sub_cats else 'None'}\n"
        display_text += f"🎯 Based on {len(self.selected_manifests)} selected inspiration games"
        
        self.randomized_display.setText(display_text)
        self.apply_roll_button.setEnabled(True)
        
        # Reset AI content
        self.ai_content = None
        self.ai_content_display.clear()
        self.apply_button.setEnabled(False)
    
    def _apply_roll(self):
        """Apply the randomized parameters"""
        if not self.randomized_data:
            QMessageBox.warning(self, "No Roll", "Please roll the dice first to generate random parameters.")
            return
        
        if not self.selected_manifests:
            QMessageBox.warning(self, "No Games Selected", "Please select inspiration games first (Auto or Manual).")
            return
        
        # Enable generate button and show user feedback
        self.generate_button.setEnabled(True)
        self.apply_roll_button.setEnabled(False)
        
        QMessageBox.information(
            self,
            "Parameters Applied!",
            f"🎯 Random parameters applied!\n\nYour personalized game will have:\n• Type: {self.randomized_data['type']}\n• Players: {self.randomized_data['players']}\n• Main Categories: {', '.join(self.randomized_data['main_categories'])}\n• Inspired by: {len(self.selected_manifests)} selected games\n\nClick 'Generate For You' to create your personalized game!"
        )
    
    def _generate_foryou(self):
        """Generate For You game content using AI"""
        if not self.randomized_data:
            QMessageBox.warning(self, "No Parameters", "Please roll and apply parameters first.")
            return
        
        if not self.selected_manifests:
            QMessageBox.warning(self, "No Games Selected", "Please select inspiration games first.")
            return
        
        try:
            # Validate API configuration
            if not is_gamai_configured():
                QMessageBox.warning(self, "API Key Required", "AI generation requires a Gemini API key. Please configure it first.")
                return
            
            # Disable buttons during generation
            self.generate_button.setEnabled(False)
            self.apply_roll_button.setEnabled(False)
            self.apply_button.setEnabled(False)
            
            # Show progress dialog
            progress_dialog = QProgressDialog("Generating personalized game content...", "Cancel", 0, 0, self)
            progress_dialog.setWindowTitle("AI Generation")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.show()
            fade_widget_in(progress_dialog, duration=200)
            
            # Collect game data
            game_data = self._collect_game_data()
            
            # Generate content in thread
            self._generate_content_async(game_data, progress_dialog)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start generation: {str(e)}")
            self._reset_generation_ui()
    
    def _generate_content_async(self, game_data, progress_dialog):
        """Generate content asynchronously"""
        def generate_worker():
            try:
                # Create AI prompt
                ai_prompt = self._create_foryou_prompt(game_data)
                
                # Call AI to generate game
                import google.generativeai as genai
                
                # Load config and get proper model (same pattern as other AI features)
                config = load_gamai_config()
                if not config.get('Key'):
                    raise ValueError("AI API key not configured")
                
                # Configure the API
                genai.configure(api_key=config['Key'])
                
                # Get model names from config - use primary model first
                primary_model = config.get('Model', 'gemini-2.5-pro')
                backup_model = config.get('BackupModel', 'gemini-2.5-flash')
                
                # Try primary model first, fallback to backup on error
                try:
                    model = genai.GenerativeModel(primary_model)
                    current_model = primary_model
                except Exception:
                    # If primary model fails (e.g., rate limit), try backup model
                    model = genai.GenerativeModel(backup_model)
                    current_model = backup_model
                
                # Generate response
                response = model.generate_content(ai_prompt)
                
                # Log which model was used
                print(f"For You game generation using model: {current_model}")
                
                # Return the full response text for display in text box
                return response.text
                    
            except Exception as e:
                error_msg = str(e)
                print(f"Content generation error: {error_msg}")
                return f"Error: {error_msg}"
        
        # Use QThread for async execution
        class ContentGenerationThread(QThread):
            finished = pyqtSignal(str)
            
            def __init__(self, worker_func):
                super().__init__()
                self.worker_func = worker_func
            
            def run(self):
                result = self.worker_func()
                self.finished.emit(result)
        
        # Store thread as instance variable to prevent garbage collection
        self.generation_thread = ContentGenerationThread(generate_worker)
        self.generation_thread.finished.connect(lambda content: self._on_content_generated(content, progress_dialog))
        self.generation_thread.finished.connect(self._cleanup_thread)
        self.generation_thread.start()
    
    def _cleanup_thread(self):
        """Clean up thread after completion"""
        if hasattr(self, 'generation_thread') and self.generation_thread is not None:
            self.generation_thread = None
    
    def _on_content_generated(self, content, progress_dialog):
        """Handle content generation completion"""
        # Only proceed if thread still exists and dialog is still active
        if not hasattr(self, 'generation_thread') or self.generation_thread is None:
            return
            
        progress_dialog.close()
        
        # Display content in text box
        self.ai_content = content
        self.ai_content_display.setPlainText(content)
        
        # Enable apply button
        self.apply_button.setEnabled(True)
        
        # Scroll to content area
        self.ai_content_display.setFocus()
        
        QMessageBox.information(
            self,
            "Content Generated!",
            "🎯 Personalized game content generated successfully!\n\nReview the content and click 'Apply For You' to create your game."
        )
        
        self._reset_generation_ui()
    
    def _reset_generation_ui(self):
        """Reset generation UI state"""
        self.generate_button.setEnabled(True)
        if self.randomized_data:
            self.apply_roll_button.setEnabled(True)
    
    def _create_foryou_prompt(self, game_data):
        """Create enhanced AI prompt for For You game generation with full manifest inspiration"""
        main_cats = ', '.join(game_data['main_categories'])
        sub_cats = ', '.join(game_data['sub_categories']) if game_data['sub_categories'] else 'None'
        
        # Enhanced format inspiration games information with COMPLETE JSON manifest data
        inspiration_analysis = []
        for i, game in enumerate(self.selected_manifests):
            # Get full game manifest details with fallbacks
            game_name = getattr(game, 'name', 'Unknown Game')
            game_version = getattr(game, 'version', 'Unknown')
            game_type = getattr(game, 'type', 'Unknown')
            game_players = getattr(game, 'players', 'Unknown')
            main_categories = getattr(game, 'main_categories', [])
            sub_categories = getattr(game, 'sub_categories', [])
            edits = getattr(game, 'edits', 0)
            played_times = getattr(game, 'played_times', 0)
            created_date = getattr(game, 'created', 'Unknown')
            time_played = getattr(game, 'time_played', {})
            
            # Handle rating and feedback with proper null handling
            rating = getattr(game, 'rating', None)
            feedback = getattr(game, 'feedback', None)
            
            # Convert to display values - use "null" for empty/None values
            if rating is None or rating == [] or rating == '':
                rating_display = 'null'
            else:
                rating_display = str(rating)
                
            if feedback is None or feedback == [] or feedback == '':
                feedback_display = 'null'
            else:
                feedback_display = str(feedback)
            
            # Extract and analyze categories
            categories_str = ', '.join([cat for cat in main_categories if cat != 'null']) if main_categories else 'Unknown'
            subcats_str = ', '.join([cat for cat in sub_categories if cat != 'null']) if sub_categories else 'Unknown'
            
            # Extract time played - ONLY minutes value as requested
            time_minutes = 0
            if time_played and isinstance(time_played, dict):
                time_minutes = time_played.get('minutes', 0)
            
            # Format creation date for readability - Extract date part only (YYYY-MM-DD)
            if created_date != 'Unknown' and created_date:
                # Simply extract the first 10 characters to get YYYY-MM-DD from ISO format
                created_formatted = created_date[:10] if len(created_date) >= 10 else created_date
            else:
                created_formatted = 'Unknown'
            
            inspiration_analysis.append(f"""Game {i+1}: {game_name}
  📊 Version: {game_version}
  🎮 Type: {game_type}
  👥 Players: {game_players}
  🏷️ Primary Categories: {categories_str}
  🏷️ Sub-Categories: {subcats_str}
  ⏱️ Time Played: {time_minutes} minutes
  📈 Play Sessions: {played_times} times
  ✏️ Custom Edits: {edits} modifications
  ⭐ Rating: {rating_display}
  💬 Feedback: {feedback_display}
  📅 Created: {created_formatted}""")
        
        inspiration_text = '\n'.join(inspiration_analysis)
        
        # Analyze user's gaming patterns using ALL manifest metadata
        all_main_cats = []
        all_sub_cats = []
        all_types = []
        all_players = []
        total_plays = 0
        total_minutes = 0
        total_edits = 0
        creation_dates = []
        
        for game in self.selected_manifests:
            main_categories = getattr(game, 'main_categories', [])
            sub_categories = getattr(game, 'sub_categories', [])
            game_type = getattr(game, 'type', 'Unknown')
            game_players = getattr(game, 'players', 'Unknown')
            played_times = getattr(game, 'played_times', 0)
            edits = getattr(game, 'edits', 0)
            created_date = getattr(game, 'created', 'Unknown')
            time_played = getattr(game, 'time_played', {})
            rating = getattr(game, 'rating', None)
            feedback = getattr(game, 'feedback', None)
            
            # Extract time played minutes
            time_minutes = 0
            if time_played and isinstance(time_played, dict):
                time_minutes = time_played.get('minutes', 0)
            
            all_main_cats.extend([cat for cat in main_categories if cat != 'null'])
            all_sub_cats.extend([cat for cat in sub_categories if cat != 'null'])
            if game_type != 'Unknown':
                all_types.append(game_type)
            if game_players != 'Unknown':
                all_players.append(game_players)
            total_plays += played_times if played_times else 0
            total_minutes += time_minutes
            total_edits += edits
            if created_date != 'Unknown':
                creation_dates.append(created_date)
        
        # Find dominant patterns
        from collections import Counter
        main_cat_counts = Counter(all_main_cats)
        sub_cat_counts = Counter(all_sub_cats)
        type_counts = Counter(all_types)
        players_counts = Counter(all_players)
        
        top_main_cats = [cat for cat, count in main_cat_counts.most_common(3)]
        top_sub_cats = [cat for cat, count in sub_cat_counts.most_common(5)]
        preferred_type = type_counts.most_common(1)[0][0] if type_counts else "2D"
        preferred_players = players_counts.most_common(1)[0][0] if players_counts else "1"
        
        # Calculate engagement metrics
        avg_minutes = total_minutes // len(self.selected_manifests) if self.selected_manifests else 0
        avg_plays = total_plays // len(self.selected_manifests) if self.selected_manifests else 0
        avg_edits = total_edits // len(self.selected_manifests) if self.selected_manifests else 0
        
        # Analyze ratings and feedback with proper null handling
        ratings_list = []
        feedback_list = []
        for game in self.selected_manifests:
            rating = getattr(game, 'rating', None)
            feedback = getattr(game, 'feedback', None)
            
            # Only add numeric ratings to the list
            if rating is not None and rating != [] and rating != '':
                try:
                    # Try to convert to float for calculation
                    rating_num = float(rating)
                    ratings_list.append(rating_num)
                except (ValueError, TypeError):
                    # If it's not a number, skip it for averaging
                    pass
            
            # Add feedback if it exists and is not empty
            if feedback is not None and feedback != [] and feedback != '':
                feedback_list.append(str(feedback))
        
        # Calculate average rating safely
        avg_rating = sum(ratings_list) / len(ratings_list) if ratings_list else 0
        rating_coverage = len(ratings_list) / len(self.selected_manifests) * 100
        
        # Determine engagement level
        if avg_minutes > 60 or avg_plays > 15:
            engagement_level = "Deep engagement - loves immersive, lengthy experiences"
        elif avg_minutes > 20 or avg_plays > 5:
            engagement_level = "Moderate engagement - enjoys satisfying game sessions"
        else:
            engagement_level = "Casual engagement - prefers quick, accessible gameplay"
        
        # Determine creativity level based on edits
        if avg_edits > 5:
            creativity_level = "High creativity - likely enjoys customization and modification"
        elif avg_edits > 2:
            creativity_level = "Moderate creativity - willing to tweak and personalize"
        else:
            creativity_level = "Standard creativity - prefers games as designed"
        
        pattern_analysis = f"""🎯 COMPREHENSIVE GAMING PROFILE ANALYSIS:
• Dominant Categories: {', '.join(top_main_cats[:3]) if top_main_cats else 'Varied preferences'}
• Preferred Gameplay Styles: {', '.join(top_sub_cats[:5]) if top_sub_cats else 'Diverse styles'}
• Preferred Perspective: {preferred_type}
• Preferred Player Count: {preferred_players} player(s)
• Total Play Sessions: {total_plays} sessions across {len(self.selected_manifests)} games
• Total Time Investment: {total_minutes} minutes ({total_minutes//60}h {total_minutes%60}m)
• Average Session Length: {avg_minutes} minutes per game
• Average Replay Value: {avg_plays} plays per game
• Customization Tendency: {avg_edits} average edits per game
• Average Rating: {avg_rating:.1f}/5 ({len(ratings_list)} rated games, {rating_coverage:.1f}% coverage)
• Feedback Coverage: {len(feedback_list)} games with feedback comments
• Engagement Profile: {engagement_level}
• Creativity Profile: {creativity_level}
• Collection Timeline: {len(creation_dates)} games with creation dates tracked"""
        
        prompt = f"""You are an expert HTML5 game designer creating a personalized game for a specific user profile. You have access to detailed user gaming data and must create a focused, engaging HTML5 game that matches their proven preferences.

## USER PROFILE ANALYSIS:
### Gaming Collection Overview:
{inspiration_text}

### Pattern Analysis:
{pattern_analysis}

## GAME DESIGN BRIEF:
Create an HTML5 game with these specifications:
- **Game Type**: {game_data['type']} 
- **Player Count**: {game_data['players']} player(s)
- **Primary Categories**: {main_cats}
- **Sub-Categories**: {sub_cats}

## DESIGN STRATEGY:
Based on the user's gaming data, this game should:

**Core Mechanics Alignment:**
- Primary mechanics should draw from the user's top preferred categories: {', '.join(top_main_cats[:3]) if top_main_cats else 'varied preferences'}
- Secondary mechanics should blend their preferred styles: {', '.join(top_sub_cats[:3]) if top_sub_cats else 'diverse styles'}
- Visual perspective should match their {preferred_type} preference
- Player experience should suit their {preferred_players} player preference

**Engagement Calibration:**
- Design session length around their {avg_minutes}-minute average attention span
- Include {avg_plays}-session replay value based on their play patterns
- Account for their {engagement_level} engagement style
- Consider their {avg_edits} average customization tendency

## TECHNICAL REQUIREMENTS:
1. **Single HTML5 file** with embedded CSS and JavaScript
2. **Complete game loop** with clear objectives and feedback systems
3. **Responsive design** that works on various screen sizes
4. **Smooth gameplay mechanics** with proper collision detection, scoring, and win/lose conditions
5. **Visual polish** with appropriate animations and sound effects
6. **Balanced difficulty** that matches their proven gaming patterns

## CRITICAL CONSTRAINTS:
- **NO meta-commentary**: The game itself should not contain references to being "made for you" or contain AI commentary
- **NO literal data usage**: Do not use exact names, versions, or manifest data in the game content
- **Focus on gameplay**: Prioritize actual game mechanics over presentation text
- **Original concept**: Create a unique game that synthesizes their preferences naturally
- **Professional polish**: Treat this as a commercial-quality HTML5 game

## GAME STRUCTURE REQUIREMENTS:
- **Clear game title** that fits the game concept (not manifest-related)
- **Main menu** with straightforward game options (start, settings, etc.)
- **Gameplay screen** with the core game mechanics
- **Score/progress system** appropriate to the game type
- **Game over/victory conditions** with restart options
- **Professional UI** that matches the game's aesthetic

Create a complete, polished HTML5 game that demonstrates deep understanding of the user's gaming preferences through its mechanics and design, not through explicit commentary about personalization.

```html
[Complete HTML5 game code here]
```"""
        return prompt
    
    def _apply_foryou(self):
        """Apply the For You game creation"""
        if not self.ai_content:
            QMessageBox.warning(self, "No Content", "No AI generated content to apply. Please generate content first.")
            return
        
        if not self.randomized_data:
            QMessageBox.warning(self, "No Parameters", "No randomized parameters found. Please roll the dice first.")
            return
        
        if not self.selected_manifests:
            QMessageBox.warning(self, "No Games Selected", "No inspiration games found. Please select games first.")
            return
        
        # Extract HTML from the generated content
        game_data = self._collect_game_data()
        html_content = self._extract_html_from_response(self.ai_content)
        
        if not html_content:
            QMessageBox.critical(self, "Content Error", "Could not extract valid HTML content from AI response. Please regenerate the content.")
            return
        
        # Create the actual game files
        parent_window = self.parent()
        if not parent_window or not hasattr(parent_window, 'game_service'):
            QMessageBox.critical(self, "Error", "Unable to access game service")
            return
        
        # Create the game using the existing method
        new_game = self._create_generated_game(game_data, html_content, parent_window)
        
        if new_game:
            self.generated_game_name = new_game.name  # Use the actual name returned by create_game
            
            # Show success message
            QMessageBox.information(
                parent_window,
                "For You Game Created Successfully!",
                f"🎯 For You game '{self.generated_game_name}' has been created and added to your collection!\n\nThis game was crafted specifically for you based on your {len(self.selected_manifests)} selected inspiration games!"
            )
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Creation Failed",
                "Failed to create the For You game. Please try again."
            )
    
    def _collect_game_data(self):
        """Collect game data from randomized parameters and selected manifests"""
        if not self.randomized_data:
            raise ValueError("No randomized game data available")
        
        return {
            "name": "For_You",
            "version": "0.0.0",
            "type": self.randomized_data["type"],
            "players": self.randomized_data["players"],
            "main_categories": self.randomized_data["main_categories"],
            "sub_categories": self.randomized_data["sub_categories"],
            "inspiration_games": [game.name for game in self.selected_manifests]
        }
    
    def _extract_html_from_response(self, response_text):
        """Extract HTML content from AI response"""
        try:
            # Look for HTML code blocks
            import re
            html_pattern = r'```html\s*\n(.*?)\n```'
            matches = re.findall(html_pattern, response_text, re.DOTALL)
            
            if matches:
                html_content = matches[0].strip()
                # Basic validation
                if html_content.lower().startswith('<!doctype') or '<html' in html_content.lower():
                    return html_content
            
            # Fallback: look for any code blocks
            code_pattern = r'```\s*\n(.*?)\n```'
            matches = re.findall(code_pattern, response_text, re.DOTALL)
            
            if matches:
                potential_html = matches[0].strip()
                # Basic validation
                if potential_html.lower().startswith('<!doctype') or '<html' in potential_html.lower():
                    return potential_html
            
            # If no code blocks found, check if the entire response is HTML
            if response_text.lower().startswith('<!doctype') or '<html' in response_text.lower():
                return response_text.strip()
            
            return None
            
        except Exception as e:
            print(f"Error extracting HTML from response: {e}")
            return None
    
    def _create_generated_game(self, game_data, html_content, parent_window):
        """Create the actual game files - using the same pattern as SurpriseGameDialog"""
        try:
            # Use the game service to create the game
            new_game = parent_window.game_service.create_game(
                name=game_data["name"],
                version=game_data["version"],
                game_type=game_data["type"],
                players=game_data["players"],
                main_categories=game_data["main_categories"],
                sub_categories=game_data["sub_categories"]
            )
            
            if not new_game:
                return False
            
            # Write the generated HTML content to index.html
            with open(new_game.html_path, 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            # Refresh the games list
            updated_games = parent_window.game_service.discover_games()
            parent_window.games = updated_games
            parent_window.game_list.display_games(updated_games)
            
            # Highlight the new game after a brief delay
            QTimer.singleShot(500, lambda: parent_window.game_list.highlight_game(self.generated_game_name))
            
            return new_game
            
        except Exception as e:
            print(f"Error creating For You game: {e}")
            return None
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=300)
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=250, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=250, hide_after=True)
        super().reject()


class ForYouGameSelectionDialog(QDialog):
    """Dialog for manually selecting games for For You inspiration"""
    
    def __init__(self, available_games, parent=None):
        super().__init__(parent)
        self.available_games = available_games
        self.setWindowTitle("Select Inspiration Games")
        self.setFixedSize(600, 500)
        self.setModal(True)
        self.selected_games = []
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Title
        title_label = QLabel("Select up to 5 games for inspiration:")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; margin-bottom: 15px; color: #CCCCCC;")
        layout.addWidget(title_label)
        
        # Game list with checkboxes
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        self.checkboxes = []
        for i, game in enumerate(self.available_games):
            # Get detailed game information
            game_name = getattr(game, 'name', 'Unknown Game')
            game_version = getattr(game, 'version', 'Unknown')
            game_type = getattr(game, 'type', 'Unknown')
            game_players = getattr(game, 'players', 'Unknown')
            main_categories = getattr(game, 'main_categories', [])
            sub_categories = getattr(game, 'sub_categories', [])
            played_times = getattr(game, 'played_times', 0)
            edits = getattr(game, 'edits', 0)
            created_date = getattr(game, 'created', 'Unknown')
            time_played = getattr(game, 'time_played', {})
            
            # Handle rating and feedback with proper null handling
            rating = getattr(game, 'rating', None)
            feedback = getattr(game, 'feedback', None)
            
            # Convert to display values - use "null" for empty/None values
            if rating is None or rating == [] or rating == '':
                rating_display = 'null'
            else:
                rating_display = str(rating)
                
            if feedback is None or feedback == [] or feedback == '':
                feedback_display = 'null'
            else:
                feedback_display = str(feedback)
            
            # Format categories
            categories_str = ', '.join([cat for cat in main_categories if cat != 'null']) if main_categories else 'Unknown'
            subcats_str = ', '.join([cat for cat in sub_categories if cat != 'null']) if sub_categories else 'Unknown'
            
            # Extract time played - ONLY minutes as requested
            time_minutes = 0
            if time_played and isinstance(time_played, dict):
                time_minutes = time_played.get('minutes', 0)
            
            # Format creation date
            if created_date != 'Unknown' and created_date:
                created_formatted = created_date[:10] if len(created_date) >= 10 else created_date
            else:
                created_formatted = 'Unknown'
            
            # Create enhanced checkbox text with complete manifest data
            checkbox_text = f"{game_name} (v{game_version})"
            checkbox_text += f" | 🎮 {game_type} | 👥 {game_players}"
            if categories_str != 'Unknown':
                checkbox_text += f" | 🏷️ {categories_str[:25]}{'...' if len(categories_str) > 25 else ''}"
            checkbox_text += f" | ⏱️ {time_minutes}min | 📊 {played_times} | ✏️ {edits}"
            
            checkbox = QCheckBox(checkbox_text)
            checkbox.setStyleSheet("""
                QCheckBox {
                    color: white;
                    font-size: 11px;
                    padding: 8px;
                    border-bottom: 1px solid #3a3a3a;
                }
                QCheckBox:hover {
                    background-color: #2a2a2a;
                }
            """)
            
            # Add comprehensive tooltip with all manifest data
            tooltip_text = f"🎮 Game: {game_name}\n"
            tooltip_text += f"📊 Version: {game_version}\n"
            tooltip_text += f"🎯 Type: {game_type}\n"
            tooltip_text += f"👥 Players: {game_players}\n"
            tooltip_text += f"🏷️ Primary Categories: {categories_str}\n"
            tooltip_text += f"🏷️ Sub-Categories: {subcats_str}\n"
            tooltip_text += f"⏱️ Time Played: {time_minutes} minutes\n"
            tooltip_text += f"📈 Play Sessions: {played_times}\n"
            tooltip_text += f"✏️ Custom Edits: {edits}\n"
            tooltip_text += f"⭐ Rating: {rating_display}\n"
            tooltip_text += f"💬 Feedback: {feedback_display}\n"
            tooltip_text += f"📅 Created: {created_formatted}"
            checkbox.setToolTip(tooltip_text)
            
            checkbox.stateChanged.connect(lambda state, idx=i: self._on_checkbox_changed(idx))
            self.checkboxes.append(checkbox)
            scroll_layout.addWidget(checkbox)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Selection info
        self.selection_label = QLabel("Selected: 0/5 games")
        self.selection_label.setStyleSheet("font-size: 14px; color: #E5E5E5; margin: 10px 0;")
        layout.addWidget(self.selection_label)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:hover {
                border: 2px solid #E5E5E5;
            }
        """)
        self.select_all_button.clicked.connect(self._select_all)
        button_layout.addWidget(self.select_all_button)
        
        button_layout.addStretch()
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:hover {
                border: 2px solid #E5E5E5;
            }
        """)
        self.clear_button.clicked.connect(self._clear_all)
        button_layout.addWidget(self.clear_button)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #666;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:hover {
                border: 2px solid #888;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        self.ok_button = QPushButton("OK")
        self.ok_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:hover {
                border: 2px solid #E5E5E5;
            }
        """)
        self.ok_button.clicked.connect(self._accept_selection)
        button_layout.addWidget(self.ok_button)
        
        layout.addLayout(button_layout)
    
    def _on_checkbox_changed(self, index):
        """Handle checkbox state changes"""
        selected_count = sum(checkbox.isChecked() for checkbox in self.checkboxes)
        
        # Limit to 5 selections
        if selected_count > 5:
            # Uncheck the currently changed checkbox
            self.checkboxes[index].setChecked(False)
            QMessageBox.information(self, "Selection Limit", "You can select a maximum of 5 games.")
            return
        
        self.selection_label.setText(f"Selected: {selected_count}/5 games")
        
        # Update button states
        if selected_count > 0:
            self.ok_button.setEnabled(True)
        else:
            self.ok_button.setEnabled(False)
    
    def _select_all(self):
        """Select all available games (up to 5)"""
        selected_count = 0
        for i, checkbox in enumerate(self.checkboxes):
            if selected_count < 5:
                checkbox.setChecked(True)
                selected_count += 1
            else:
                checkbox.setChecked(False)
        
        self.selection_label.setText(f"Selected: {selected_count}/5 games")
        self.ok_button.setEnabled(True)
    
    def _clear_all(self):
        """Clear all selections"""
        for checkbox in self.checkboxes:
            checkbox.setChecked(False)
        
        self.selection_label.setText("Selected: 0/5 games")
        self.ok_button.setEnabled(False)
    
    def _accept_selection(self):
        """Accept the current selection"""
        self.selected_games = []
        for i, checkbox in enumerate(self.checkboxes):
            if checkbox.isChecked():
                self.selected_games.append(self.available_games[i])
        
        if not self.selected_games:
            QMessageBox.information(self, "No Selection", "Please select at least one game.")
            return
        
        self.accept()
    
    def get_selected_games(self):
        """Get the list of selected games"""
        return self.selected_games


class GameOptionsDialog(QDialog):
    """Dialog for choosing between Play and Edit options"""
    
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setWindowTitle(f"Game Options - {game.name}")
        self.setFixedSize(520, 720)  # Increased height by 100px to accommodate long game names and category info
        self.setModal(True)
        self.choice = None
        self.info_label = None  # Store reference to info label for updates
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)  # Optimized from 20px for better space efficiency
        
        # Game icon
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(160, 160)  # Slightly larger icon for bigger dialog
        
        if self.game.icon_path and self.game.icon_path.exists():
            pixmap = QPixmap(str(self.game.icon_path))
            icon_label.setPixmap(pixmap.scaled(160, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            # Fallback: create text icon
            pixmap = QPixmap(160, 160)
            pixmap.fill(QColor(0, 0, 0))
            painter = QPainter(pixmap)
            painter.setPen(QColor(255, 255, 255))
            font = QFont("Arial", 40, QFont.Bold)  # Slightly larger font for bigger icon
            painter.setFont(font)
            initials = "".join(word[0] for word in self.game.name.split() if word).upper()[:2]
            painter.drawText(pixmap.rect(), Qt.AlignCenter, initials)
            painter.end()
            icon_label.setPixmap(pixmap)
        
        layout.addWidget(icon_label)
        
        # Create scrollable info container for long game names and category information
        info_container = QScrollArea()
        info_container.setWidgetResizable(True)
        info_container.setMaximumHeight(250)  # Limit height to prevent infinite expansion
        info_container.setStyleSheet("QScrollArea { border: 1px solid #555; border-radius: 5px; background-color: #2a2a2a; }")
        info_container.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        # Game info widget
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(15, 10, 15, 10)
        info_layout.setSpacing(8)
        
        # Game info with categories
        main_cat_display = format_categories_for_display(self.game.main_categories, "Main-Category", MAIN_CATEGORIES)
        sub_cat_display = format_categories_for_display(self.game.sub_categories, "Sub-Category", SUB_CATEGORIES)
        
        # Format auto-tracking information
        # Format auto-tracking information - show total minutes only
        total_minutes = (self.game.time_played.get('minutes', 0) + 
                        self.game.time_played.get('hours', 0) * 60 + 
                        self.game.time_played.get('days', 0) * 24 * 60 + 
                        self.game.time_played.get('weeks', 0) * 7 * 24 * 60 + 
                        self.game.time_played.get('months', 0) * 30 * 24 * 60)
        time_display = f"Time: {total_minutes}m"
        edits_display = f"Edits: {self.game.edits}"
        played_display = f"Played: {self.game.played_times} times"  # NEW: Game launch count
        # Format rating information
        rating_display = f"Rating: {self.game.get_rating_display()} ({self.game.get_rating_text()})"
        # NEW: Format feedback information
        feedback_display = f"Feedbacks {self.game.get_feedback_count()}"
        
        # Split info into multiple labels for better readability and scrollability
        name_label = QLabel(f"🎮 {self.game.name}")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; margin-bottom: 8px;")
        name_label.setWordWrap(True)
        
        version_label = QLabel(f"📦 Version {self.game.version}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: #ccc; font-size: 14px; margin-bottom: 8px;")
        
        type_label = QLabel(f"Type: {self.game.type} | Players: {self.game.players}")
        type_label.setAlignment(Qt.AlignCenter)
        type_label.setStyleSheet("color: #ccc; font-size: 14px; margin-bottom: 8px;")
        
        cat_label = QLabel(f"{main_cat_display} | {sub_cat_display}")
        cat_label.setAlignment(Qt.AlignCenter)
        cat_label.setStyleSheet("color: #E5E5E5; font-size: 13px; margin-bottom: 8px;")
        cat_label.setWordWrap(True)
        
        stats_label = QLabel(f"{time_display} | {edits_display} | {played_display}")
        stats_label.setAlignment(Qt.AlignCenter)
        stats_label.setStyleSheet("color: #E5E5E5; font-size: 13px; margin-bottom: 8px;")
        
        rating_label = QLabel(f"{rating_display}")
        rating_label.setAlignment(Qt.AlignCenter)
        rating_label.setStyleSheet("color: #E5E5E5; font-size: 14px; font-weight: bold; margin-bottom: 8px;")
        
        feedback_label = QLabel(f"{feedback_display}")
        feedback_label.setAlignment(Qt.AlignCenter)
        feedback_label.setStyleSheet("color: #E5E5E5; font-size: 13px; font-weight: bold;")
        
        info_layout.addWidget(name_label)
        info_layout.addWidget(version_label)
        info_layout.addWidget(type_label)
        info_layout.addWidget(cat_label)
        info_layout.addWidget(stats_label)
        info_layout.addWidget(rating_label)
        info_layout.addWidget(feedback_label)
        info_layout.addStretch()
        
        info_container.setWidget(info_widget)
        layout.addWidget(info_container)
        
        # Choice buttons
        button_layout = QVBoxLayout()
        button_layout.setSpacing(10)
        
        self.play_button = QPushButton("▶ Play Game")
        self.play_button.setFixedSize(200, 50)
        self.play_button.setCursor(Qt.PointingHandCursor)
        self.play_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.play_button.clicked.connect(lambda: self._choose("play"))
        
        self.edit_button = QPushButton("✎ Edit Code")
        self.edit_button.setFixedSize(200, 50)
        self.edit_button.setCursor(Qt.PointingHandCursor)
        self.edit_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.edit_button.clicked.connect(lambda: self._choose("edit"))
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(200, 40)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addWidget(self.play_button)
        button_layout.addWidget(self.edit_button)
        
        # Rating button
        self.rate_button = QPushButton("⭐ Rate Game")
        self.rate_button.setFixedSize(200, 40)
        self.rate_button.setCursor(Qt.PointingHandCursor)
        self.rate_button.clicked.connect(self._rate_game)
        self.rate_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        button_layout.addWidget(self.rate_button)
        
        # NEW: Feedback button
        self.feedback_button = QPushButton("💬 Feedback")
        self.feedback_button.setFixedSize(200, 40)
        self.feedback_button.setCursor(Qt.PointingHandCursor)
        self.feedback_button.clicked.connect(self._open_feedback_manager)
        self.feedback_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        button_layout.addWidget(self.feedback_button)
        
        # Delete button
        self.delete_button = QPushButton("🗑️ Delete Game")
        self.delete_button.setFixedSize(200, 40)
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.clicked.connect(self._delete_game)
        self.delete_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        button_layout.addWidget(self.delete_button)
        
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)
        
        # Set dialog background
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
            QCheckBox {
                color: white;
                font-size: 13px;
            }
        """)  # Search dialog pattern styling
        
        # Center dialog
        layout.addStretch()
    
    def _choose(self, choice):
        self.choice = choice
        self.accept()
    
    def _rate_game(self):
        """Open rating dialog for the game"""
        dialog = RatingDialog(self.game.rating, self.game.name, self)
        if dialog.exec_() == QDialog.Accepted:
            new_rating = dialog.get_selected_rating()
            if new_rating != self.game.rating:  # Only save if rating changed
                try:
                    self.game.set_rating(new_rating)
                    # Refresh the info display to show new rating
                    self._update_rating_display()
                    QMessageBox.information(self, "Rating Saved", f"Rating for '{self.game.name}' has been updated to {self.game.get_rating_text()}!")
                except ValueError as e:
                    QMessageBox.warning(self, "Invalid Rating", str(e))
    
    def _open_feedback_manager(self):
        """Open feedback manager dialog for the game"""
        dialog = FeedbackDialog(self.game, self)
        if dialog.exec_() == QDialog.Accepted:
            # Refresh the info display to show updated feedback count
            self._update_feedback_display()
            QMessageBox.information(self, "Feedback Updated", f"Feedback for '{self.game.name}' has been updated!")
    
    def _update_feedback_display(self):
        """Update the feedback information in the info container"""
        # Since we can't easily update individual labels in the scroll area,
        # we'll reopen the dialog to refresh the display
        pass  # This is handled by the user reopening the dialog
    
    def _update_rating_display(self):
        """Update the rating information in the info label"""
        if not self.info_label:
            return  # Safety check
        
        # Game info with categories
        main_cat_display = format_categories_for_display(self.game.main_categories, "Main-Category", MAIN_CATEGORIES)
        sub_cat_display = format_categories_for_display(self.game.sub_categories, "Sub-Category", SUB_CATEGORIES)
        
        # Format auto-tracking information
        # Format auto-tracking information - show total minutes only
        total_minutes = (self.game.time_played.get('minutes', 0) + 
                        self.game.time_played.get('hours', 0) * 60 + 
                        self.game.time_played.get('days', 0) * 24 * 60 + 
                        self.game.time_played.get('weeks', 0) * 7 * 24 * 60 + 
                        self.game.time_played.get('months', 0) * 30 * 24 * 60)
        time_display = f"Time: {total_minutes}m"
        edits_display = f"Edits: {self.game.edits}"
        played_display = f"Played: {self.game.played_times} times"  # NEW: Game launch count
        # Format rating information
        rating_display = f"Rating: {self.game.get_rating_display()} ({self.game.get_rating_text()})"
        
        # Update the existing info label text
        self.info_label.setText(f"{self.game.name}\nVersion {self.game.version}\nType: {self.game.type} | Players: {self.game.players}\n{main_cat_display} | {sub_cat_display}\n{time_display} | {edits_display} | {played_display}\n{rating_display}")
    
    def _delete_game(self):
        """Delete the game after confirmation"""
        # Show confirmation dialog
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to delete '{self.game.name}'?\n\n"
            "This will permanently delete the game folder and all its files.\n"
            "This action cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Get parent window to access game service
                parent_window = self.parent()
                if parent_window and hasattr(parent_window, 'game_service'):
                    # Clean up the game name and delete the game using the game service
                    game_name_clean = self.game.name.strip()
                    success = parent_window.game_service.delete_game(game_name_clean)
                    
                    if success:
                        # Refresh the games list
                        updated_games = parent_window.game_service.discover_games()
                        parent_window.games = updated_games
                        
                        # Update display based on current filter state
                        if hasattr(parent_window, 'is_filtered') and parent_window.is_filtered and hasattr(parent_window, 'current_filtered_games'):
                            if parent_window.current_filtered_games:
                                # Update filtered games list
                                parent_window.current_filtered_games = [g for g in updated_games if g.name in [fg.name for fg in parent_window.current_filtered_games]]
                                parent_window.game_list.display_games(parent_window.current_filtered_games)
                            else:
                                parent_window.game_list.display_games(updated_games)
                        else:
                            parent_window.game_list.display_games(updated_games)
                        
                        # Show success message
                        QMessageBox.information(
                            parent_window,
                            "Game Deleted",
                            f"Game '{game_name_clean}' has been deleted successfully!"
                        )
                        
                        # Close the dialog
                        self.reject()
                    else:
                        QMessageBox.critical(
                            self, 
                            "Delete Error", 
                            f"Failed to delete game '{game_name_clean}'.\n\n"
                            f"Possible reasons:\n"
                            f"• Game folder not found\n"
                            f"• Permission denied\n"
                            f"• Game name mismatch\n\n"
                            f"Please check if the game folder exists and try again."
                        )
                else:
                    QMessageBox.critical(self, "Delete Error", "Unable to access game service.")
            except Exception as e:
                QMessageBox.critical(
                    self, 
                    "Delete Error", 
                    f"An error occurred while deleting the game: {str(e)}"
                )


class ViewToggleButton(QPushButton):
    """Toggle button for switching between vertical and grid view layouts"""
    
    # Signal to notify when view changes
    viewChanged = pyqtSignal(bool)  # True for grid view, False for vertical view
    
    def __init__(self, is_grid_view=False, parent=None):
        super().__init__(parent)
        self.is_grid_view = is_grid_view
        self.setFixedSize(50, 40)  # Same size as search button
        self.setCursor(Qt.PointingHandCursor)
        self._update_appearance()
        self.clicked.connect(self._toggle_view)
    
    def _update_appearance(self):
        """Update button appearance based on current view mode"""
        if self.is_grid_view:
            # Grid view - show vertical lines (⋮)
            icon_text = "⋮"
            tooltip = "Switch to Vertical View"
            border_color = "#E5E5E5"  # Purple for grid view
            hover_border = "#E5E5E5"
            pressed_border = "#E5E5E5"
        else:
            # Vertical view - show horizontal lines (≡)
            icon_text = "≡"
            tooltip = "Switch to Grid View"
            border_color = "#E5E5E5"  # Green for vertical view
            hover_border = "#E5E5E5"
            pressed_border = "#E5E5E5"
        
        self.setText(icon_text)
        self.setToolTip(tooltip)
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid {border_color};
                color: white;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid {hover_border};
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid {pressed_border};
            }}
        """)
    
    def _toggle_view(self):
        """Toggle between vertical and grid view"""
        self.is_grid_view = not self.is_grid_view
        self._update_appearance()
        
        # Emit signal to notify parent of view change
        self.viewChanged.emit(self.is_grid_view)
    
    def set_view_mode(self, is_grid):
        """Set the view mode programmatically"""
        self.is_grid_view = is_grid
        self._update_appearance()
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=200)
    
    def closeEvent(self, event):
        """Close dialog with fade-out animation"""
        fade_widget_out(self, duration=150, hide_after=False)
        event.accept()
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=150, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=150, hide_after=True)
        super().reject()


class IconOptionsDialog(QDialog):
    """Dialog for icon management options"""
    
    def __init__(self, game, game_service, parent=None):
        super().__init__(parent)
        self.game = game
        self.game_service = game_service
        self.setWindowTitle(f"Icon Options - {game.name}")
        self.setFixedSize(400, 450)
        self.setModal(True)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the icon options dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title_label = QLabel("🖼️ Icon Management")
        title_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold; margin-bottom: 20px;")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Current icon preview (if exists)
        if self.game.icon_path and self.game.icon_path.exists():
            icon_label = QLabel()
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setFixedSize(100, 100)
            pixmap = QPixmap(str(self.game.icon_path))
            icon_label.setPixmap(pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            layout.addWidget(icon_label)
        else:
            no_icon_label = QLabel("No icon found")
            no_icon_label.setStyleSheet("color: #999; font-size: 14px;")
            no_icon_label.setAlignment(Qt.AlignCenter)
            no_icon_label.setFixedSize(100, 100)
            no_icon_label.setStyleSheet("""
                QLabel {
                    border: 2px dashed #555;
                    border-radius: 5px;
                    background-color: #333;
                    color: #999;
                    font-size: 14px;
                }
            """)
            layout.addWidget(no_icon_label)
        
        # Option buttons
        self.remove_button = QPushButton("🗑️ Remove Icon")
        self.remove_button.setFixedSize(200, 40)
        self.remove_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.remove_button.clicked.connect(self._remove_icon)
        layout.addWidget(self.remove_button)
        
        self.default_button = QPushButton("✨ Default Icon")
        self.default_button.setFixedSize(200, 40)
        self.default_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.default_button.clicked.connect(self._set_default_icon)
        layout.addWidget(self.default_button)
        
        self.custom_button = QPushButton("🎨 Custom Icon")
        self.custom_button.setFixedSize(200, 40)
        self.custom_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.custom_button.clicked.connect(self._custom_icon)
        layout.addWidget(self.custom_button)
        
        layout.addStretch()
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setFixedSize(100, 35)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        layout.addWidget(self.cancel_button)
    
    def _remove_icon(self):
        """Remove the game's icon"""
        # Confirmation dialog
        reply = QMessageBox.question(
            self, 
            "Confirm Removal", 
            "Are you sure you want to remove the icon? This will delete the icon.png file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                if self.game.icon_path and self.game.icon_path.exists():
                    self.game.icon_path.unlink()
                    QMessageBox.information(self, "Success", "Icon removed successfully!")
                    self.accept()
                else:
                    QMessageBox.information(self, "Info", "No icon file found to remove.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to remove icon: {e}")
    
    def _set_default_icon(self):
        """Set the default icon for the game"""
        # Confirmation dialog
        reply = QMessageBox.question(
            self, 
            "Confirm Default Icon", 
            "Replace the current icon with the default icon?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Construct the proper icon path from the game's folder
                icon_path = self.game.folder_path / "icon.png"
                
                # Use the GameService's _create_default_icon method
                if self.game_service and hasattr(self.game_service, '_create_default_icon'):
                    self.game_service._create_default_icon(icon_path)
                    
                    # Update the game's icon_path to point to the new icon
                    self.game.icon_path = icon_path
                    
                    QMessageBox.information(self, "Success", "Default icon set successfully!")
                    self.accept()
                else:
                    QMessageBox.critical(self, "Error", "Game service not available.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to set default icon: {e}")
    
    def _custom_icon(self):
        """Custom icon option - select and set custom icon"""
        try:
            # Check if PIL is available for image validation
            if not HAS_PIL:
                QMessageBox.warning(
                    self, 
                    "Feature Unavailable", 
                    "Image processing library (PIL) is not available.\n"
                    "Please install Pillow to use custom icon feature."
                )
                return
            
            # Open file dialog to select PNG image
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Custom Icon",
                "",
                "PNG Images (*.png);;All Files (*)"
            )
            
            if not file_path:
                # User cancelled the file selection
                return
            
            # Validate file exists
            if not os.path.exists(file_path):
                QMessageBox.critical(self, "Error", "Selected file does not exist.")
                return
            
            # Check if it's a PNG file
            if not file_path.lower().endswith('.png'):
                QMessageBox.warning(self, "Invalid File Type", "Please select a PNG image file.")
                return
            
            # Validate image size (must be 200x200)
            try:
                from PIL import Image
                with Image.open(file_path) as img:
                    width, height = img.size
                    if width != 200 or height != 200:
                        QMessageBox.warning(
                            self, 
                            "Invalid Image Size", 
                            f"Image size must be 200x200 pixels.\n\n"
                            f"Current size: {width}x{height} pixels"
                        )
                        return
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to read image: {e}")
                return
            
            # Check if icon already exists
            icon_path = self.game.folder_path / "icon.png"
            if icon_path.exists():
                reply = QMessageBox.question(
                    self,
                    "Replace Icon",
                    "An icon already exists. Do you want to replace it?",
                    QMessageBox.Yes | QMessageBox.No
                )
                
                if reply == QMessageBox.No:
                    return
            
            # Copy the selected image to the game folder as icon.png
            try:
                shutil.copy2(file_path, str(icon_path))
                
                # Update the game's icon_path to point to the new icon
                self.game.icon_path = icon_path
                
                QMessageBox.information(self, "Success", "Custom icon set successfully!")
                self.accept()
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to copy icon: {e}")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process custom icon: {e}")


class SearchEngineDialog(QDialog):
    """Advanced search and filter dialog for the main menu"""
    
    def __init__(self, games, parent=None):
        super().__init__(parent)
        self.games = games
        self.filtered_games = games.copy()
        self._setup_ui()
        self._setup_search_logic()
    
    def _setup_ui(self):
        """Setup the search dialog UI"""
        self.setWindowTitle("Game Search Engine")
        self.setFixedSize(950, 800)  # Increased size for better search option accommodation
        self.setModal(True)
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)
        
        # Title
        title_label = QLabel("🎮 Game Search Engine")
        title_label.setStyleSheet("color: white; font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Create scroll area for large options
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        # Content widget for scroll area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(20)
        
        # 1. Name Search Section
        self._create_name_search_section(content_layout)
        
        # 2. Filter Sections
        self._create_filter_sections(content_layout)
        
        # 3. Sort Section
        self._create_sort_section(content_layout)
        
        # Set content widget to scroll area
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)
        
        # 4. Action Buttons
        self._create_action_buttons(main_layout)
        
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
            QLineEdit {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                font-size: 14px;
            }
            QComboBox {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 5px;
                font-size: 14px;
            }
            QListWidget {
                background-color: #333;
                color: white;
                border: 1px solid #555;
                border-radius: 3px;
            }
            QCheckBox {
                color: white;
                font-size: 13px;
            }
            QRadioButton {
                color: white;
                font-size: 13px;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton#search_button {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
            }
            QPushButton#search_button:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton#search_button:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton#clear_button {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
            }
            QPushButton#clear_button:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton#clear_button:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton#cancel_button {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
            }
            QPushButton#cancel_button:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton#cancel_button:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
    
    def _create_name_search_section(self, parent_layout):
        """Create name search input section"""
        name_group = QGroupBox("🔍 Search by Name")
        name_layout = QVBoxLayout(name_group)
        
        # Search input
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Enter game name or keywords (e.g., 'candy', 'cru', 'puzzle')")
        self.name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 15px;
                color: white;
                font-size: 14px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QLineEdit:hover {
                border-color: #555555;
            }
        """)
        self.name_input.textChanged.connect(self._on_name_changed)
        name_layout.addWidget(self.name_input)
        
        # Search info
        info_label = QLabel("💡 Search is case-insensitive and matches partial names")
        info_label.setStyleSheet("color: #ccc; font-size: 11px;")
        name_layout.addWidget(info_label)
        
        parent_layout.addWidget(name_group)
    
    def _create_filter_sections(self, parent_layout):
        """Create all filter sections"""
        # Type Filter
        type_group = QGroupBox("🎮 Game Type")
        type_layout = QVBoxLayout(type_group)
        
        self.type_2d_checkbox = QCheckBox("2D Games")
        self.type_2d_checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
        self.type_3d_checkbox = QCheckBox("3D Games")
        self.type_3d_checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
        type_layout.addWidget(self.type_2d_checkbox)
        type_layout.addWidget(self.type_3d_checkbox)
        
        parent_layout.addWidget(type_group)
        
        # Players Filter
        players_group = QGroupBox("👥 Number of Players")
        players_layout = QVBoxLayout(players_group)
        
        self.players_1_checkbox = QCheckBox("Single Player (1)")
        self.players_1_checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
        self.players_2_checkbox = QCheckBox("Two Players (2)")
        self.players_2_checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
        players_layout.addWidget(self.players_1_checkbox)
        players_layout.addWidget(self.players_2_checkbox)
        
        parent_layout.addWidget(players_group)
        
        # Main Categories Filter
        main_cat_group = QGroupBox("🏷️ Main Categories")
        main_cat_layout = QVBoxLayout(main_cat_group)
        
        # Create scroll area for categories
        main_cat_scroll = QScrollArea()
        main_cat_scroll.setMaximumHeight(200)  # Increased from 120
        main_cat_scroll.setWidgetResizable(True)
        main_cat_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        main_cat_widget = QWidget()
        main_cat_list_layout = QVBoxLayout(main_cat_widget)
        
        self.main_category_checkboxes = {}
        for category in MAIN_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_filters_changed)
            main_cat_list_layout.addWidget(checkbox)
            self.main_category_checkboxes[category] = checkbox
        
        main_cat_list_layout.addStretch()
        main_cat_scroll.setWidget(main_cat_widget)
        main_cat_layout.addWidget(main_cat_scroll)
        
        parent_layout.addWidget(main_cat_group)
        
        # Sub Categories Filter
        sub_cat_group = QGroupBox("🏷️ Sub Categories")
        sub_cat_layout = QVBoxLayout(sub_cat_group)
        
        # Create scroll area for sub categories
        sub_cat_scroll = QScrollArea()
        sub_cat_scroll.setMaximumHeight(250)  # Increased from 120
        sub_cat_scroll.setWidgetResizable(True)
        sub_cat_scroll.setStyleSheet("QScrollArea { border: 1px solid #555; }")
        
        sub_cat_widget = QWidget()
        sub_cat_list_layout = QVBoxLayout(sub_cat_widget)
        
        self.sub_category_checkboxes = {}
        for category in SUB_CATEGORIES:
            checkbox = QCheckBox(category)
            checkbox.setStyleSheet("QCheckBox { color: white; font-size: 13px; }")
            checkbox.stateChanged.connect(self._on_filters_changed)
            sub_cat_list_layout.addWidget(checkbox)
            self.sub_category_checkboxes[category] = checkbox
        
        sub_cat_list_layout.addStretch()
        sub_cat_scroll.setWidget(sub_cat_widget)
        sub_cat_layout.addWidget(sub_cat_scroll)
        
        parent_layout.addWidget(sub_cat_group)
        
        # Version Filter
        version_group = QGroupBox("📦 Version Status")
        version_layout = QVBoxLayout(version_group)
        
        self.version_all_radio = QRadioButton("All Versions")
        self.version_all_radio.setStyleSheet("QRadioButton { color: white; font-size: 13px; }")
        self.version_beta_radio = QRadioButton("Beta (< 1.0.0)")
        self.version_beta_radio.setStyleSheet("QRadioButton { color: white; font-size: 13px; }")
        self.version_final_radio = QRadioButton("Final (>= 1.0.0)")
        self.version_final_radio.setStyleSheet("QRadioButton { color: white; font-size: 13px; }")
        
        self.version_all_radio.setChecked(True)
        
        version_layout.addWidget(self.version_all_radio)
        version_layout.addWidget(self.version_beta_radio)
        version_layout.addWidget(self.version_final_radio)
        
        # Connect version radio buttons
        self.version_all_radio.toggled.connect(self._on_filters_changed)
        self.version_beta_radio.toggled.connect(self._on_filters_changed)
        self.version_final_radio.toggled.connect(self._on_filters_changed)
        
        parent_layout.addWidget(version_group)
    
    def _create_sort_section(self, parent_layout):
        """Create sorting section"""
        sort_group = QGroupBox("📊 Sort Results")
        sort_layout = QVBoxLayout(sort_group)
        
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "Name (A-Z)",
            "Name (Z-A)", 
            "Most Played Time",
            "Least Played Time",
            "Most Played Times",
            "Least Played Times",
            "Most Edits",
            "Least Edits",
            "Highest Rated",      # NEW: Rating sort
            "Lowest Rated"        # NEW: Rating sort
        ])
        self.sort_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                padding: 10px;
                color: white;
                font-size: 14px;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid white;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #3a3a3a;
                selection-background-color: #E5E5E5;
                selection-color: black;
            }
        """)
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)
        sort_layout.addWidget(self.sort_combo)
        
        parent_layout.addWidget(sort_group)
    
    def _create_action_buttons(self, parent_layout):
        """Create action buttons"""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        # Search button
        self.search_button = QPushButton("🔍 Search")
        self.search_button.setObjectName("search_button")
        self.search_button.clicked.connect(self._apply_search_and_close)
        button_layout.addWidget(self.search_button)
        
        # Clear button
        self.clear_button = QPushButton("🗑️ Clear All")
        self.clear_button.setObjectName("clear_button")
        self.clear_button.clicked.connect(self._clear_all_filters)
        button_layout.addWidget(self.clear_button)
        
        # Cancel button
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("cancel_button")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        
        parent_layout.addLayout(button_layout)
        
        # Results count label
        self.results_label = QLabel(f"Showing {len(self.filtered_games)} of {len(self.games)} games")
        self.results_label.setStyleSheet("color: #E5E5E5; font-weight: bold; margin-top: 5px;")
        self.results_label.setAlignment(Qt.AlignCenter)
        parent_layout.addWidget(self.results_label)
    
    def _setup_search_logic(self):
        """Setup real-time search logic"""
        # Initialize with all games
        self._update_results_count()
    
    def _on_name_changed(self):
        """Handle name search input changes"""
        self._on_filters_changed()
    
    def _on_filters_changed(self):
        """Handle filter changes (for real-time search)"""
        QTimer.singleShot(300, self._perform_search)  # Debounce search
    
    def _on_sort_changed(self):
        """Handle sort changes"""
        self._perform_search()
    
    def _perform_search(self):
        """Perform the actual search and filtering"""
        self.filtered_games = self.games.copy()
        
        # Apply name search
        name_filter = self.name_input.text().strip().lower()
        if name_filter:
            self.filtered_games = [
                game for game in self.filtered_games
                if name_filter in game.name.lower()
            ]
        
        # Apply type filter
        active_types = []
        if self.type_2d_checkbox.isChecked():
            active_types.append("2D")
        if self.type_3d_checkbox.isChecked():
            active_types.append("3D")
        
        if active_types:
            self.filtered_games = [
                game for game in self.filtered_games
                if game.type in active_types
            ]
        
        # Apply players filter
        active_players = []
        if self.players_1_checkbox.isChecked():
            active_players.append("1")
        if self.players_2_checkbox.isChecked():
            active_players.append("2")
        
        if active_players:
            self.filtered_games = [
                game for game in self.filtered_games
                if game.players in active_players
            ]
        
        # Apply main category filter
        selected_main_cats = [
            cat for cat, checkbox in self.main_category_checkboxes.items()
            if checkbox.isChecked()
        ]
        
        if selected_main_cats:
            self.filtered_games = [
                game for game in self.filtered_games
                if any(cat in game.main_categories for cat in selected_main_cats)
            ]
        
        # Apply sub category filter
        selected_sub_cats = [
            cat for cat, checkbox in self.sub_category_checkboxes.items()
            if checkbox.isChecked()
        ]
        
        if selected_sub_cats:
            self.filtered_games = [
                game for game in self.filtered_games
                if any(cat in game.sub_categories for cat in selected_sub_cats)
            ]
        
        # Apply version filter
        if self.version_beta_radio.isChecked():
            self.filtered_games = [
                game for game in self.filtered_games
                if self._is_beta_version(game.version)
            ]
        elif self.version_final_radio.isChecked():
            self.filtered_games = [
                game for game in self.filtered_games
                if not self._is_beta_version(game.version)
            ]
        
        # Apply sorting
        self._apply_sorting()
        
        # Update results count
        self._update_results_count()
    
    def _is_beta_version(self, version_str):
        """Check if version is beta (< 1.0.0)"""
        try:
            # Handle common version formats
            version_str = version_str.strip()
            if not version_str or version_str.lower() in ['n/a', 'unknown']:
                return True  # Consider unknown versions as beta
            
            # Remove prefix/suffix like 'v', 'beta', etc.
            cleaned = version_str.lower()
            if cleaned.startswith('v'):
                cleaned = cleaned[1:]
            
            # Split by dots and convert to numbers
            parts = cleaned.split('.')
            version_numbers = []
            for part in parts:
                try:
                    # Handle cases like "0.9.9-beta"
                    number_part = ''.join(c for c in part if c.isdigit())
                    if number_part:
                        version_numbers.append(int(number_part))
                except ValueError:
                    continue
            
            # Pad with zeros if needed
            while len(version_numbers) < 3:
                version_numbers.append(0)
            
            # Compare against 1.0.0
            return version_numbers < [1, 0, 0]
        except:
            return True  # If parsing fails, assume beta
    
    def _apply_sorting(self):
        """Apply sorting to filtered games"""
        sort_option = self.sort_combo.currentText()
        
        if sort_option == "Name (A-Z)":
            self.filtered_games.sort(key=lambda g: g.name.lower())
        elif sort_option == "Name (Z-A)":
            self.filtered_games.sort(key=lambda g: g.name.lower(), reverse=True)
        elif sort_option == "Most Played Time":
            self.filtered_games.sort(key=self._get_total_playtime, reverse=True)
        elif sort_option == "Least Played Time":
            self.filtered_games.sort(key=self._get_total_playtime)
        elif sort_option == "Most Played Times":
            self.filtered_games.sort(key=lambda g: g.played_times, reverse=True)
        elif sort_option == "Least Played Times":
            self.filtered_games.sort(key=lambda g: g.played_times)
        elif sort_option == "Most Edits":
            self.filtered_games.sort(key=lambda g: g.edits, reverse=True)
        elif sort_option == "Least Edits":
            self.filtered_games.sort(key=lambda g: g.edits)
        elif sort_option == "Highest Rated":
            self.filtered_games.sort(key=lambda g: (g.rating if g.rating is not None else 0), reverse=True)
        elif sort_option == "Lowest Rated":
            self.filtered_games.sort(key=lambda g: (g.rating if g.rating is not None else 0))
    
    def _get_total_playtime(self, game):
        """Calculate total playtime in minutes for sorting"""
        time_data = game.time_played
        if not isinstance(time_data, dict):
            return 0
        
        return (
            time_data.get('minutes', 0) +
            time_data.get('hours', 0) * 60 +
            time_data.get('days', 0) * 24 * 60 +
            time_data.get('weeks', 0) * 7 * 24 * 60 +
            time_data.get('months', 0) * 30 * 24 * 60
        )
    
    def _clear_all_filters(self):
        """Clear all filters and reset to default state"""
        # Clear name search
        self.name_input.clear()
        
        # Clear type filters
        self.type_2d_checkbox.setChecked(False)
        self.type_3d_checkbox.setChecked(False)
        
        # Clear players filters
        self.players_1_checkbox.setChecked(False)
        self.players_2_checkbox.setChecked(False)
        
        # Clear category filters
        for checkbox in self.main_category_checkboxes.values():
            checkbox.setChecked(False)
        for checkbox in self.sub_category_checkboxes.values():
            checkbox.setChecked(False)
        
        # Reset version filter
        self.version_all_radio.setChecked(True)
        
        # Reset sort to default
        self.sort_combo.setCurrentText("Name (A-Z)")
        
        # Trigger search update
        self._perform_search()
    
    def _update_results_count(self):
        """Update the results count label"""
        total = len(self.games)
        shown = len(self.filtered_games)
        self.results_label.setText(f"Showing {shown} of {total} games")
        
        if shown == total:
            self.results_label.setStyleSheet("color: #E5E5E5; font-weight: bold; margin-top: 5px;")
        else:
            self.results_label.setStyleSheet("color: #E5E5E5; font-weight: bold; margin-top: 5px;")
    
    def _apply_search_and_close(self):
        """Perform search and close dialog with acceptance"""
        self._perform_search()
        self.accept()
    
    def get_filtered_games(self):
        """Return the filtered games list"""
        return self.filtered_games
    
    def showEvent(self, event):
        """Show dialog with fade-in animation"""
        super().showEvent(event)
        fade_widget_in(self, duration=250)
    
    def closeEvent(self, event):
        """Close dialog with fade-out animation"""
        fade_widget_out(self, duration=200, hide_after=False)
        event.accept()
    
    def accept(self):
        """Accept dialog with fade-out animation"""
        fade_widget_out(self, duration=200, hide_after=True)
        super().accept()
    
    def reject(self):
        """Reject dialog with fade-out animation"""
        fade_widget_out(self, duration=200, hide_after=True)
        super().reject()


class GamaiApiKeyDialog(QDialog):
    """Dialog for setting up GAMAI API key"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GAMAI API Key Setup")
        self.setFixedSize(500, 300)
        self.setModal(True)
        self.api_key = ""
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout()
        
        # Header
        header_label = QLabel("🔑 Set Up GAMAI API Key")
        header_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: white;
                margin-bottom: 15px;
            }
        """)
        layout.addWidget(header_label)
        
        # Instructions
        instructions = QLabel("""
        To use GAMAI AI assistant features, you need to set up your Google Gemini API key.
        
        Steps:
        1. Go to https://makersuite.google.com/app/apikey
        2. Create or select a project
        3. Generate an API key
        4. Paste it below
        """)
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #666; margin-bottom: 10px;")
        layout.addWidget(instructions)
        
        # API Key Input
        key_label = QLabel("API Key:")
        key_label.setStyleSheet("font-weight: bold; margin-top: 10px; color: #CCCCCC;")
        layout.addWidget(key_label)
        
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("Enter your Gemini API key...")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                border: 2px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
                color: white;
                background-color: #2a2a2a;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
        """)
        layout.addWidget(self.api_key_input)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 4px;
                font-weight: bold;
                color: white;
                padding: 10px 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.save_button.clicked.connect(self._save_api_key)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 4px;
                color: white;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
        self.setLayout(layout)
    
    def _save_api_key(self):
        api_key = self.api_key_input.text().strip()
        if not api_key:
            QMessageBox.warning(self, "Error", "Please enter an API key.")
            return
        
        if update_gamai_key(api_key):
            self.api_key = api_key
            self.accept()
        else:
            QMessageBox.critical(self, "Error", "Failed to save API key. Please try again.")


class GamaiChatDialog(QDialog):
    """Chat dialog for GAMAI AI assistant"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GAMAI - AI Assistant")
        self.setMinimumSize(700, 600)
        self.setModal(False)  # Allow interaction with main window
        self.model = None
        self.current_model_name = None  # Track which model is currently active
        self.context_type = "main"  # Main menu context
        self.conversation_history = GAMAI_CONTEXT.get_context("main")
        GAMAI_CONTEXT.set_active_context("main")
        self._setup_ui()
        self._initialize_ai()
        
        # Install event filter for the message input
        self.message_input.installEventFilter(self)
    
    def _setup_ui(self):
        layout = QVBoxLayout()
        
        # Header
        header_layout = QHBoxLayout()
        
        header_label = QLabel("✨ GAMAI - Gamebox Assistant")
        header_label.setStyleSheet("""
            QLabel {
                font-size: 18px;
                font-weight: bold;
                color: white;
                margin-bottom: 10px;
            }
        """)
        header_layout.addWidget(header_label)
        
        header_layout.addStretch()
        
        # Status indicator
        self.status_label = QLabel("● Ready")
        self.status_label.setStyleSheet("color: #E5E5E5; font-size: 12px;")
        header_layout.addWidget(self.status_label)
        
        layout.addLayout(header_layout)
        
        # Chat area
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #ddd;
                border-radius: 5px;
                padding: 10px;
                font-size: 14px;
                line-height: 1.4;
                color: black;
            }
        """)
        layout.addWidget(self.chat_area)
        
        # Input area
        input_layout = QHBoxLayout()
        
        self.message_input = QTextEdit()
        self.message_input.setPlaceholderText("Type your message here... (Shift+Enter for new line)")
        self.message_input.setMaximumHeight(80)
        self.message_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 5px;
                padding: 8px;
                font-size: 14px;
                color: black;
            }
            QTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        
        # Event filter will handle Enter key
        
        input_layout.addWidget(self.message_input)
        
        # Send button
        self.send_button = QPushButton("Send")
        self.send_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
                min-width: 80px;
                padding: 15px 25px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.send_button.clicked.connect(self._send_message)
        
        input_layout.addWidget(self.send_button)
        
        layout.addLayout(input_layout)
        
        # Clear conversation button
        clear_layout = QHBoxLayout()
        clear_layout.addStretch()
        
        self.clear_button = QPushButton("Clear Conversation")
        self.clear_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 4px;
                color: white;
                padding: 8px 16px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.clear_button.clicked.connect(self._clear_conversation)
        
        clear_layout.addWidget(self.clear_button)
        layout.addLayout(clear_layout)
        
        self.setLayout(layout)
    
    def _initialize_ai(self):
        """Initialize the AI model"""
        if not HAS_GEMINI_AI:
            self._add_message("system", "❌ Gemini AI not available. Please install the Google Generative AI library.")
            self.send_button.setEnabled(False)
            return
        
        config = load_gamai_config()
        if not config.get('Key'):
            self._add_message("system", "❌ No API key configured. Please set up your Gemini API key first.")
            self.send_button.setEnabled(False)
            return
        
        try:
            genai.configure(api_key=config['Key'])
            primary_model = config.get('Model', 'gemini-2.5-pro')
            self.model = genai.GenerativeModel(primary_model)
            self.current_model_name = primary_model  # Track current model
            self._add_message("system", f"✅ GAMAI ready! Using {primary_model}. I'm here to help with game-related questions and assistance.")
        except Exception as e:
            self._add_message("system", f"❌ Failed to initialize AI: {str(e)}")
            self.send_button.setEnabled(False)
    
    def eventFilter(self, obj, event):
        """Handle key press events for message input"""
        if obj == self.message_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() == Qt.ShiftModifier:
                # Shift+Enter = allow normal behavior (new line)
                return False  # Let normal event handling occur
            elif event.key() == Qt.Key_Return:
                # Enter = send message
                self._send_message()
                return True  # Consume the event
        return super().eventFilter(obj, event)
    
    def _send_message(self):
        """Send message to AI"""
        if not self.message_input.toPlainText().strip() or not self.model:
            return
        
        user_message = self.message_input.toPlainText().strip()
        self.message_input.clear()
        
        # Add user message to chat
        self._add_message("user", user_message)
        
        # Add to conversation history using context manager
        self.conversation_history.append({"role": "user", "content": user_message})
        GAMAI_CONTEXT.add_message(self.context_type, "user", user_message)
        
        # Show typing indicator
        self.send_button.setEnabled(False)
        self.status_label.setText("● Thinking...")
        
        # Generate response
        self._generate_response(user_message)
    
    def _generate_response(self, user_message):
        """Generate AI response"""
        ai_response = ""
        
        try:
            # Get current config
            config = load_gamai_config()
            
            # Get persona based on context (for now, use default)
            persona = config.get("Personas", {}).get("Default", GAMAI_PERSONA)
            
            # Create context-aware prompt
            context_messages = self.conversation_history.copy()
            context_messages.insert(0, {"role": "system", "content": persona})
            
            # Convert to simple text for now
            full_prompt = persona + "\n\n" + "\n".join([msg["content"] for msg in context_messages])
            
            # Try primary model first
            try:
                response = self.model.generate_content(full_prompt)
                ai_response = response.text
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check if it's a rate limit error
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    # Try backup model (flash)
                    self.status_label.setText("● Rate limit reached, switching to Flash...")
                    self._switch_to_backup_model()
                    
                    try:
                        response = self.model.generate_content(full_prompt)
                        ai_response = response.text
                        self._add_message("system", "🔄 Switched to Flash model due to Pro rate limit.")
                        
                    except Exception as e2:
                        error_msg2 = str(e2).lower()
                        
                        # Both models failed
                        if "rate limit" in error_msg2 or "quota" in error_msg2 or "limit" in error_msg2:
                            ai_response = "❌ API rate limit reached for both Pro and Flash models. Please wait before trying again or check your API key quotas."
                        else:
                            ai_response = f"❌ Error with Flash model: {str(e2)}"
                            
                else:
                    ai_response = f"❌ Error: {str(e)}"
            
        except Exception as e:
            ai_response = f"❌ Configuration error: {str(e)}"
        
        # Add AI response to chat
        self._add_message("assistant", ai_response)
        self.conversation_history.append({"role": "assistant", "content": ai_response})
        GAMAI_CONTEXT.add_message(self.context_type, "assistant", ai_response)
        
        # Reset UI
        self.send_button.setEnabled(True)
        self.status_label.setText("● Ready")
    
    def _add_message(self, sender, message):
        """Add message to chat display"""
        timestamp = datetime.now().strftime("%H:%M")
        
        if sender == "user":
            html = f"""
            <div style="margin: 10px 0; text-align: right;">
                <div style="display: inline-block; background: #E5E5E5; color: black; 
                           padding: 8px 12px; border-radius: 15px; max-width: 70%;">
                    <strong>You:</strong> {message.replace(chr(10), '<br>')}
                    <div style="font-size: 11px; opacity: 0.8; margin-top: 5px;">{timestamp}</div>
                </div>
            </div>
            """
        elif sender == "assistant":
            html = f"""
            <div style="margin: 10px 0; text-align: left;">
                <div style="display: inline-block; background: #E5E5E5; color: black; 
                           padding: 8px 12px; border-radius: 15px; max-width: 70%;">
                    <strong>✨ GAMAI:</strong> {message.replace(chr(10), '<br>')}
                    <div style="font-size: 11px; opacity: 0.8; margin-top: 5px;">{timestamp}</div>
                </div>
            </div>
            """
        else:  # system message
            html = f"""
            <div style="margin: 10px 0; text-align: center;">
                <div style="display: inline-block; background: #E5E5E5; color: black; 
                           padding: 8px 12px; border-radius: 10px; font-style: italic;">
                    {message}
                    <div style="font-size: 11px; opacity: 0.7; margin-top: 5px;">{timestamp}</div>
                </div>
            </div>
            """
        
        self.chat_area.append(html)
        # Scroll to bottom
        cursor = self.chat_area.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_area.setTextCursor(cursor)
    
    def _switch_to_backup_model(self):
        """Switch to backup model (Flash)"""
        try:
            config = load_gamai_config()
            backup_model_name = config.get("BackupModel", "gemini-2.5-flash")
            
            if backup_model_name and backup_model_name != self.current_model_name:
                genai.configure(api_key=config.get("Key", ""))
                self.model = genai.GenerativeModel(backup_model_name)
                self.current_model_name = backup_model_name
                
        except Exception as e:
            print(f"Failed to switch to backup model: {e}")
    
    def _clear_conversation(self):
        """Clear the conversation history"""
        self.conversation_history.clear()
        GAMAI_CONTEXT.clear_context(self.context_type)
        self.chat_area.clear()
        self._add_message("system", "🔄 Conversation cleared. How can I help you?")


class GamaiMainMenuDialog(QDialog):
    """Main menu dialog for GAMAI options"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("GAMAI Assistant")
        self.setFixedSize(500, 550)  # Increased height: +50px up, +50px down (total +100px)
        self.setModal(True)
        self.option_selected = None
        self._setup_ui()
    
    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 30, 30, 30)  # Add margins for better visibility
        layout.setSpacing(15)  # Reduced spacing: 15px first, then button increases
        
        # Header
        header_label = QLabel("✨ GAMAI Assistant")
        header_label.setStyleSheet("""
            QLabel {
                font-size: 28px;
                font-weight: bold;
                color: #E5E5E5;
                margin-bottom: 25px;
                text-align: center;
                background: transparent;
            }
        """)
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        subtitle_label = QLabel("Choose an option:")
        subtitle_label.setStyleSheet("""
            QLabel {
                font-size: 18px; 
                color: white;
                margin-bottom: 40px;
                text-align: center;
                background: transparent;
            }
        """)
        subtitle_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(subtitle_label)
        
        # Options with explicit styling
        self.chat_button = QPushButton("💬 Chat")
        self.chat_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 10px;
                color: white;
                padding: 33px 40px 43px 40px;
                font-size: 18px;
                font-weight: bold;
                margin: 12px 20px;
                min-width: 200px;
                text-align: center;
                line-height: 0.8;
                font-family: Arial, sans-serif;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.chat_button.clicked.connect(lambda: self._select_option("chat"))
        layout.addWidget(self.chat_button)
        
        self.create_game_button = QPushButton("🎮 Create Game")
        self.create_game_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 3px solid #E5E5E5;
                border-radius: 10px;
                padding: 33px 40px 43px 40px;  /* Increased 5px up and down + 10px down + 10px up and down */
                font-size: 18px;
                font-weight: bold;
                margin: 12px 20px;
                min-width: 200px;
                text-align: center;
                line-height: 0.8;
                font-family: Arial, sans-serif;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 3px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 3px solid #2a2a2a;
            }
        """)
        self.create_game_button.clicked.connect(lambda: self._select_option("create_game"))
        layout.addWidget(self.create_game_button)
        
        self.import_game_button = QPushButton("📁 Import Game")
        self.import_game_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 3px solid #E5E5E5;
                border-radius: 10px;
                padding: 33px 40px 43px 40px;  /* Increased 5px up and down + 10px down + 10px up and down */
                font-size: 18px;
                font-weight: bold;
                margin: 12px 20px;
                min-width: 200px;
                text-align: center;
                line-height: 0.8;
                font-family: Arial, sans-serif;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 3px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 3px solid #E5E5E5;
            }
        """)
        self.import_game_button.clicked.connect(lambda: self._select_option("import_game"))
        layout.addWidget(self.import_game_button)
        
        layout.addStretch()
        
        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                padding: 10px 20px;
                font-size: 14px;
                margin-top: 10px;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        layout.addWidget(cancel_button)
        
        self.setLayout(layout)
    
    def _select_option(self, option):
        """Handle option selection"""
        self.option_selected = option
        self.accept()
    
    def get_selected_option(self):
        """Get the selected option"""
        return self.option_selected


class GamaiChatWidget(QWidget):
    """Embedded chat widget for editor and game modes"""
    
    def __init__(self, context_type="default", parent=None):
        super().__init__(parent)
        self.context_type = context_type  # "editor", "game", or "global" 
        self.model = None
        self.current_model_name = None
        
        # Map context type to display names for user interface
        self.display_names = {
            "global": "Global",
            "editor": "Editor", 
            "game": "Game",
            "main": "Main Menu"
        }
        
        # Store current mode for display purposes
        self.current_mode = context_type
        
        # Store references for game operations
        self.main_window = None  # Will be set to GameBox instance
        self.game_list = None    # Will be set to GameList instance
        
        # Find main window for game operations
        self._find_main_window()
        
        # Always use global context for seamless conversation
        self.conversation_history = GAMAI_CONTEXT.get_context("global")
        GAMAI_CONTEXT.set_active_context("global")
        
        self.is_visible = True
        self._setup_ui()
        self._initialize_ai()
    
    def _find_main_window(self):
        """Find the main GameBox window for game operations"""
        try:
            print(f"🔍 _find_main_window: Starting search...")
            parent = self.parent()
            print(f"🔍 _find_main_window: Starting parent: {parent} (type: {type(parent)})")
            
            depth = 0
            while parent:
                depth += 1
                print(f"🔍 _find_main_window: Depth {depth} - Parent: {parent} (type: {type(parent)})")
                print(f"🔍 _find_main_window: Has game_player: {hasattr(parent, 'game_player')}")
                print(f"🔍 _find_main_window: Has _open_editor: {hasattr(parent, '_open_editor')}")
                
                if hasattr(parent, 'game_player') and hasattr(parent, '_open_editor'):
                    self.main_window = parent
                    print(f"🎯 _find_main_window: FOUND GameBox! Setting main_window = {parent}")
                    
                    # Also set the game_list reference if available
                    if hasattr(parent, 'game_list'):
                        self.game_list = parent.game_list
                        print(f"✅ _find_main_window: Set game_list = {parent.game_list}")
                    else:
                        print(f"⚠️ _find_main_window: Parent has no 'game_list' attribute")
                    break
                parent = parent.parent()
                if depth > 10:  # Safety limit
                    print(f"❌ _find_main_window: Safety limit reached, stopping search")
                    break
                    
            if not self.main_window:
                print(f"❌ _find_main_window: Could not find GameBox with game_player and _open_editor")
                print(f"🔍 _find_main_window: Final parent: {parent}")
                
        except Exception as e:
            print(f"❌ Error in _find_main_window: {e}")
            import traceback
            traceback.print_exc()
    
    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)  # More spacious layout
        layout.setSpacing(10)
        
        # Compact header (as requested - smaller text)
        # Use display names mapping for clean UI
        display_name = self.display_names.get(self.context_type, self.context_type.title())
        title_label = QLabel(f"GAMAI ({display_name})")
        title_label.setStyleSheet("""
            QLabel {
                font-size: 12px;  /* Smaller font */
                font-weight: bold;
                color: #E5E5E5;
                margin-bottom: 8px;
                background: transparent;
            }
        """)
        layout.addWidget(title_label)
        
        # Full-width chat area (takes most space)
        self.chat_area = QTextEdit()
        self.chat_area.setReadOnly(True)
        self.chat_area.setMinimumHeight(300)  # More space for chat
        self.chat_area.setStyleSheet("""
            QTextEdit {
                background-color: #E5E5E5;
                border: 1px solid #ddd;
                border-radius: 8px;
                padding: 10px;
                font-size: 13px;
                line-height: 1.4;
                color: black;
                margin-bottom: 8px;
            }
        """)
        layout.addWidget(self.chat_area)
        
        # Full-width input area at bottom
        self.message_input = QTextEdit()
        self.message_input.setMinimumHeight(80)
        self.message_input.setMaximumHeight(120)
        self.message_input.setPlaceholderText("Type your message for GAMAI (Global Context)...")
        self.message_input.setStyleSheet("""
            QTextEdit {
                border: 2px solid #ddd;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: black;
                background-color: white;
            }
            QTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        layout.addWidget(self.message_input)
        
        # Send button (full width)
        self.send_button = QPushButton("Send Message")
        self.send_button.setMinimumHeight(35)
        self.send_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 6px;
                color: white;
                font-size: 14px;
                font-weight: bold;
                padding: 8px;
                margin-top: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.send_button.clicked.connect(self._send_message)
        layout.addWidget(self.send_button)
        
        self.setLayout(layout)
        
        # Set size policies for proper embedding
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.chat_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        
        # Install event filter for Enter key (F10 functionality in game/editor modes)
        self.message_input.installEventFilter(self)
        
        # Add welcome message with current mode
        display_name = self.display_names.get(self.context_type, "Assistant")
        # Use display names mapping for clean UI
        display_name = self.display_names.get(self.context_type, self.context_type.title())
        self._add_message("system", f"✨ GAMAI ready in {display_name} mode!")
    
    def _initialize_ai(self):
        """Initialize the AI model for this context"""
        if not HAS_GEMINI_AI:
            self._add_message("system", "❌ Gemini AI not available.")
            self.send_button.setEnabled(False)
            return
        
        config = load_gamai_config()
        if not config.get('Key'):
            self._add_message("system", "❌ No API key configured.")
            self.send_button.setEnabled(False)
            return
        
        try:
            genai.configure(api_key=config['Key'])
            primary_model = config.get('Model', 'gemini-2.5-pro')
            self.model = genai.GenerativeModel(primary_model)
            self.current_model_name = primary_model
        except Exception as e:
            self._add_message("system", f"❌ Failed to initialize AI: {str(e)}")
            self.send_button.setEnabled(False)
    
    def eventFilter(self, obj, event):
        """Handle key press events - F10 to send, F11 to toggle"""
        if obj == self.message_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_F10:
                self._send_message()
                return True
            elif event.key() == Qt.Key_F11:
                self.toggle_visibility()
                return True
        return super().eventFilter(obj, event)
    
    def _send_message(self):
        """Send message to AI"""
        if not self.message_input.toPlainText().strip() or not self.model:
            return
        
        user_message = self.message_input.toPlainText().strip()
        self.message_input.clear()
        
        # Add user message to chat
        self._add_message("user", user_message)
        
        # Add to conversation history using context manager
        self.conversation_history.append({"role": "user", "content": user_message})
        GAMAI_CONTEXT.add_message(self.context_type, "user", user_message)
        
        # Show typing indicator
        self.send_button.setEnabled(False)
        
        # Generate response
        self._generate_response(user_message)
    
    def _generate_response(self, user_message):
        """Generate AI response with context-aware persona and tool-calls support"""
        ai_response = ""
        
        try:
            # Get context-specific persona
            config = load_gamai_config()
            personas = config.get("Personas", {})
            
            # Only get available_games for main menu (global) context
            available_games = None
            if self.context_type == "global":
                available_games = self._get_available_games_for_context()
                games_text = ', '.join(available_games) if available_games else "No games available"
            
            if self.context_type == "editor":
                persona = personas.get("EditorChat", "You are GAMAI, helping with code editing and development.")
            elif self.context_type == "game":
                persona = personas.get("GameplayChat", "You are GAMAI, assisting with gameplay and game-related questions.")
            else:
                # Main menu AI with tool-calls support
                games_text = ', '.join(available_games) if available_games else "No games available"
                persona = personas.get("Default", 
                    f"You are GAMAI, the GameBox assistant in main menu mode. "
                    f"Available games: {games_text}. "
                    f"Available tools: play_game_name (opens game in play mode), edit_game_name (opens game in editor mode), get_tools (shows all available tools). "
                    f"CRITICAL: When users want to open ANY game, you MUST use JSON tool-calls. "
                    f"For play mode: {{\"tool\": \"play_game_name\", \"parameters\": {{\"name\": \"Game Name\"}}}} "
                    f"For edit mode: {{\"tool\": \"edit_game_name\", \"parameters\": {{\"name\": \"Game Name\"}}}} "
                    f"Examples: 'play candy crush', 'edit maser fighter', 'open game name'. "
                    f"If a game isn't found, show the user what games are available."
                )
            
            # Create context-aware prompt
            context_messages = self.conversation_history.copy()
            context_messages.insert(0, {"role": "system", "content": persona})
            
            # Debug: Print available games for AI (only for main menu context)
            if self.context_type == "global":
                print(f"🔍 AI Available Games: {available_games}")
            
            # Convert to simple text
            full_prompt = persona + "\n\n" + "\n".join([msg["content"] for msg in context_messages])
            
            # Debug: Show full prompt (truncated)
            print(f"🔍 Full AI Prompt (first 500 chars): {full_prompt[:500]}...")
            
            # Try primary model first
            try:
                response = self.model.generate_content(full_prompt)
                ai_response = response.text
                
                # Process tool-calls if in main menu context
                if self.context_type == "global":
                    print(f"🔍 Original AI response: {ai_response[:200]}...")
                    ai_response = self._process_tool_calls(ai_response)
                    print(f"🔧 After tool-calls processing: {ai_response[:200]}...")
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Handle rate limits - try backup model
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    self._switch_to_backup_model()
                    
                    try:
                        response = self.model.generate_content(full_prompt)
                        ai_response = response.text
                        self._add_message("system", "🔄 Switched to Flash model due to rate limit.")
                        
                    except Exception as e2:
                        error_msg2 = str(e2).lower()
                        
                        if "rate limit" in error_msg2 or "quota" in error_msg2 or "limit" in error_msg2:
                            ai_response = "❌ API rate limit reached for both models."
                        else:
                            ai_response = f"❌ Error: {str(e2)}"
                            
                else:
                    ai_response = f"❌ Error: {str(e)}"
            
        except Exception as e:
            ai_response = f"❌ Configuration error: {str(e)}"
        
        # Add AI response to chat
        self._add_message("assistant", ai_response)
        self.conversation_history.append({"role": "assistant", "content": ai_response})
        GAMAI_CONTEXT.add_message(self.context_type, "assistant", ai_response)
        
        # Reset UI
        self.send_button.setEnabled(True)
    
    def _switch_to_backup_model(self):
        """Switch to backup model (Flash)"""
        try:
            config = load_gamai_config()
            backup_model_name = config.get("BackupModel", "gemini-2.5-flash")
            
            if backup_model_name and backup_model_name != self.current_model_name:
                genai.configure(api_key=config.get("Key", ""))
                self.model = genai.GenerativeModel(backup_model_name)
                self.current_model_name = backup_model_name
                
        except Exception as e:
            self._add_message("system", f"❌ Failed to switch to backup model: {e}")
    
    def _add_message(self, sender, message):
        """Add message to chat display (compact format)"""
        timestamp = datetime.now().strftime("%H:%M")
        
        if sender == "user":
            html = f"""
            <div style="margin: 5px 0; text-align: right;">
                <div style="display: inline-block; background: #E5E5E5; color: black; 
                           padding: 4px 8px; border-radius: 10px; max-width: 80%; font-size: 11px;">
                    <strong>You:</strong> {message.replace(chr(10), '<br>')}
                </div>
            </div>
            """
        elif sender == "assistant":
            html = f"""
            <div style="margin: 5px 0; text-align: left;">
                <div style="display: inline-block; background: #E5E5E5; color: black; 
                           padding: 4px 8px; border-radius: 10px; max-width: 80%; font-size: 11px;">
                    <strong>✨ GAMAI:</strong> {message.replace(chr(10), '<br>')}
                </div>
            </div>
            """
        else:  # system message
            html = f"""
            <div style="margin: 5px 0; text-align: center;">
                <div style="display: inline-block; background: #E5E5E5; color: black; 
                           padding: 4px 8px; border-radius: 8px; font-size: 10px; font-style: italic;">
                    {message}
                </div>
            </div>
            """
        
        self.chat_area.append(html)
        # Scroll to bottom
        cursor = self.chat_area.textCursor()
        cursor.movePosition(cursor.End)
        self.chat_area.setTextCursor(cursor)
    
    def toggle_visibility(self):
        """Toggle widget visibility"""
        self.is_visible = not self.is_visible
        self.setVisible(self.is_visible)
    
    def showEvent(self, event):
        """Handle show event"""
        super().showEvent(event)
        self.is_visible = True
    
    def hideEvent(self, event):
        """Handle hide event"""
        super().hideEvent(event)
        self.is_visible = False
    
    def refresh_conversation_history(self):
        """Refresh conversation history from global context manager"""
        self.conversation_history = GAMAI_CONTEXT.get_context("global")
    
    def update_mode_display(self, new_mode):
        """Update the mode display in the title"""
        self.current_mode = new_mode
        display_name = self.display_names.get(new_mode, new_mode.title())
        
        # Update the title label if it exists
        for child in self.children():
            if isinstance(child, QLabel) and "GAMAI" in child.text():
                child.setText(f"GAMAI ({display_name})")
                break
        GAMAI_CONTEXT.set_active_context("global")
    
    def _get_available_games_for_context(self):
        """Get available games for AI context"""
        try:
            # Find the parent GameBox instance to get games
            parent = self.parent()
            while parent and not isinstance(parent, GameBox):
                parent = parent.parent()
            
            if parent and hasattr(parent, 'current_filtered_games'):
                return [game.name for game in parent.current_filtered_games]
            elif parent and hasattr(parent, 'games'):
                return [game.name for game in parent.games]
            else:
                return []
        except Exception as e:
            print(f"Error getting available games: {e}")
            return []
    
    def _process_tool_calls(self, ai_response):
        """Process tool-calls in AI response for main menu context"""
        try:
            # Look for JSON tool-calls in the response
            import re
            
            # Enhanced pattern to match JSON tool-calls
            json_patterns = [
                r'```json\s*({.*?})\s*```',  # Code blocks
                r'{.*?"tool".*?"play_game_name".*?"name".*?}',  # play_game_name
                r'{.*?"tool".*?"edit_game_name".*?"name".*?}',  # edit_game_name
            ]
            
            matches = []
            for pattern in json_patterns:
                matches.extend(re.findall(pattern, ai_response, re.DOTALL))
            
            if not matches:
                # Also check for non-JSON but clear intent like "I will open [game] in play mode"
                play_intent = re.search(r'(?:open|start|launch|play)\s+["\']?([A-Za-z0-9 _-]+)["\']?\s+(?:in\s+)?(?:play\s+mode)?', ai_response, re.IGNORECASE)
                edit_intent = re.search(r'(?:edit|open\s+editor|code)\s+["\']?([A-Za-z0-9 _-]+)["\']?\s+(?:in\s+)?(?:editor\s+mode)?', ai_response, re.IGNORECASE)
                
                if play_intent or edit_intent:
                    # Found clear intent but no JSON - suggest proper format
                    return ai_response + "\n\n💡 To use the game opening tools, you MUST respond with JSON format:\n```json\n# For play mode:\n{\"tool\": \"play_game_name\", \"parameters\": {\"name\": \"Game Name\"}}\n# For edit mode:\n{\"tool\": \"edit_game_name\", \"parameters\": {\"name\": \"Game Name\"}}\n```"
                
                return ai_response  # No tool-calls found
            
            tool_calls_results = []
            
            for match in matches:
                if isinstance(match, tuple):
                    json_str = match[0] or match[1]  # Get the non-empty group
                else:
                    json_str = match
                
                try:
                    tool_call = json.loads(json_str)
                    result = self._execute_tool_call(tool_call)
                    tool_calls_results.append(result)
                except json.JSONDecodeError:
                    tool_calls_results.append(f"❌ Invalid JSON format: {json_str[:100]}...")
            
            # Add tool results to AI response
            if tool_calls_results:
                results_text = "\n\n🔧 Tool Results:\n" + "\n".join(tool_calls_results)
                return ai_response + results_text
            
            return ai_response
            
        except Exception as e:
            return ai_response + f"\n\n❌ Tool processing error: {str(e)}"
    
    def _execute_tool_call(self, tool_call):
        """Execute a tool-call and return result"""
        try:
            tool_name = tool_call.get("tool", "")
            parameters = tool_call.get("parameters", {})
            
            # CONTEXT VALIDATION: Check if tool is available in current context
            current_context = self._detect_current_context()
            available_tools = self._get_available_tools_for_context(current_context)
            
            # get_tools is always available (global tool)
            if tool_name != "get_tools" and tool_name not in available_tools:
                return f"❌ Tool '{tool_name}' is not available in {current_context} context.\n\nAvailable tools in this context: {', '.join(available_tools)}\n\n💡 Use the 'get_tools' tool to see all available tools for any context."
            
            if tool_name == "play_game_name":
                game_name = parameters.get("name", "")
                if not game_name:
                    return "❌ play_game_name requires 'name' parameter"
                
                # Try to find and open the game
                success = self._open_game_by_name(game_name, "play")
                if success:
                    return f"✅ Successfully opened '{game_name}' in play mode!"
                else:
                    available_games = self._get_available_games_for_context()
                    if not available_games:
                        return f"❌ Game '{game_name}' not found. No games available."
                    else:
                        return f"❌ Game '{game_name}' not found. Available games: {', '.join(available_games)}"
            
            elif tool_name == "edit_game_name":
                game_name = parameters.get("name", "")
                if not game_name:
                    return "❌ edit_game_name requires 'name' parameter"
                
                # Try to find and open the game in edit mode
                success = self._open_game_by_name(game_name, "edit")
                if success:
                    return f"✅ Successfully opened '{game_name}' in editor mode! (Code editor should appear on screen)"
                else:
                    available_games = self._get_available_games_for_context()
                    if not available_games:
                        return f"❌ Game '{game_name}' not found. No games available."
                    else:
                        return f"❌ Game '{game_name}' not found. Available games: {', '.join(available_games)}"
            
            elif tool_name == "get_tools":
                # Global tool - available in any context
                context = self._detect_current_context()
                available_tools = self._get_available_tools_for_context(context)
                
                # Create comprehensive tool information for AI
                all_tools_info = {
                    "main_menu": {
                        "open_game_play": {
                            "name": "Open Game in Play Mode",
                            "description": "Launches a game in full-screen play mode without the editor interface",
                            "usage": "Use this when user wants to play a game directly",
                            "parameters": ["game_name (required)"],
                            "example": '{"tool": "open_game_play", "parameters": {"game_name": "pong_game"}}'
                        },
                        "open_game_editor": {
                            "name": "Open Game in Editor Mode", 
                            "description": "Launches a game with the full code editor for development",
                            "usage": "Use this when user wants to edit a game's code",
                            "parameters": ["game_name (required)"],
                            "example": '{"tool": "open_game_editor", "parameters": {"game_name": "pong_game"}}'
                        },
                        "get_games_list": {
                            "name": "Get Available Games List",
                            "description": "Returns a list of all available games in the launcher",
                            "usage": "Use this to show what games are available to play/edit",
                            "parameters": [],
                            "example": '{"tool": "get_games_list", "parameters": {}}'
                        }
                    },
                    "gameplay": {
                        "edit_selected": {
                            "name": "Edit Selected Code with AI",
                            "description": "AI-powered editing of currently selected/highlighted code in instant editor",
                            "usage": "Use this when user has highlighted code and wants AI to modify it",
                            "parameters": ["selected_code (required)", "instruction (required)"],
                            "example": '{"tool": "edit_selected", "parameters": {"selected_code": "<div>...</div>", "instruction": "change color to blue"}}'
                        },
                        "edit_code": {
                            "name": "Edit Code with AI (Full File or Lines)",
                            "description": "AI-powered code editing with support for full file or specific line ranges",
                            "usage": "Use this for comprehensive code modifications, can edit entire file or specific line ranges",
                            "parameters": ["instruction (required)", "start_line (optional)", "end_line (optional)"],
                            "example": '{"tool": "edit_code", "parameters": {"instruction": "add a function", "start_line": 5, "end_line": 10}}'
                        }
                    },
                    "editor": {
                        "edit_selected": {
                            "name": "Edit Selected Code with AI",
                            "description": "AI-powered editing of currently selected code in main editor",
                            "usage": "Use this when user has highlighted code in the main editor and wants AI to modify it",
                            "parameters": ["selected_code (required)", "instruction (required)"],
                            "example": '{"tool": "edit_selected", "parameters": {"selected_code": "<div>...</div>", "instruction": "change color to blue"}}'
                        },
                        "edit_code": {
                            "name": "Edit Code with AI (Full File or Lines)",
                            "description": "AI-powered code editing with support for full file or specific line ranges in main editor",
                            "usage": "Use this for comprehensive code modifications in the main editor, can edit entire file or specific line ranges",
                            "parameters": ["instruction (required)", "start_line (optional)", "end_line (optional)"],
                            "example": '{"tool": "edit_code", "parameters": {"instruction": "add a function", "start_line": 5, "end_line": 10}}'
                        }
                    },
                    "global": {
                        "get_tools": {
                            "name": "Get Available Tools with Descriptions",
                            "description": "Shows all available tools for the current context with detailed descriptions and usage examples",
                            "usage": "Use this when user asks about available tools or capabilities",
                            "parameters": [],
                            "example": '{"tool": "get_tools", "parameters": {}}'
                        }
                    }
                }
                
                # Build comprehensive response for AI
                response = f"🎯 **CURRENT CONTEXT: {context.upper()}**\n\n"
                
                # Add current context tools
                if context in all_tools_info:
                    response += f"📋 **{context.replace('_', ' ').title()} Tools:**\n\n"
                    for tool_name, tool_data in all_tools_info[context].items():
                        response += f"**{tool_data['name']}**\n"
                        response += f"   Description: {tool_data['description']}\n"
                        response += f"   When to use: {tool_data['usage']}\n"
                        
                        if tool_data['parameters']:
                            params = ', '.join(tool_data['parameters'])
                            response += f"   Parameters: {params}\n"
                        
                        response += f"   JSON Example: {tool_data['example']}\n\n"
                
                # Add global tools (always available)
                response += "🌐 **Global Tools (Always Available):**\n\n"
                for tool_name, tool_data in all_tools_info['global'].items():
                    response += f"**{tool_data['name']}**\n"
                    response += f"   Description: {tool_data['description']}\n"
                    response += f"   When to use: {tool_data['usage']}\n"
                    response += f"   JSON Example: {tool_data['example']}\n\n"
                
                response += "💡 **Tip:** When user asks 'what tools do you have?' or 'what can you do?', always call get_tools first!"
                
                return response
            
            elif tool_name == "edit_selected":
                # Enhanced edit selected code with smart prompt analysis
                selected_code = parameters.get("selected_code", "")
                instruction = parameters.get("instruction", "")
                editor_widget = parameters.get("editor_widget", None)
                game_file_path = parameters.get("game_file_path", "")
                prompt_analysis = parameters.get("prompt_analysis", None)
                
                if not selected_code:
                    return "❌ edit_selected requires 'selected_code' parameter"
                if not instruction:
                    return "❌ edit_selected requires 'instruction' parameter"
                
                # Call AI to edit the selected code with enhanced logic
                success = self._edit_code_with_ai(selected_code, instruction, editor_widget)
                if success:
                    return f"✅ Successfully edited selected code with AI! The code has been updated in the editor."
                else:
                    return f"❌ Failed to edit selected code with AI."
            
            elif tool_name == "edit_code":
                # Edit entire file or specific line range with AI
                instruction = parameters.get("instruction", "")
                start_line = parameters.get("start_line", None)
                end_line = parameters.get("end_line", None)
                
                print(f"🔍 DEBUG: edit_code called - instruction: '{instruction}'")
                print(f"🔍 DEBUG: edit_code called - start_line: {start_line}, end_line: {end_line}")
                
                if not instruction:
                    return "❌ edit_code requires 'instruction' parameter"
                
                # Get current editor based on context
                current_editor = None
                editor_widget = parameters.get("editor_widget", None)
                
                if editor_widget:
                    current_editor = editor_widget
                elif hasattr(self, 'main_window') and self.main_window:
                    # Check current context to determine editor
                    current_context = self._detect_current_context()
                    if current_context == "gameplay":
                        # We're in gameplay - use live editor
                        if hasattr(self.main_window, 'game_player') and self.main_window.game_player:
                            current_editor = self.main_window.game_player.live_code_editor
                    elif current_context == "editor":
                        # We're in main editor
                        if hasattr(self.main_window, 'current_editor') and self.main_window.current_editor:
                            current_editor = self.main_window.current_editor.code_editor
                
                if not current_editor:
                    return "❌ No editor found for edit_code. Make sure you're in an editing context (gameplay or main editor)."
                
                # Get file content
                current_content = current_editor.toPlainText()
                if not current_content:
                    return "❌ No content found in current editor"
                
                # Handle specific line ranges
                if start_line is not None and end_line is not None:
                    try:
                        lines = current_content.split('\n')
                        if start_line <= 0 or end_line > len(lines) or start_line > end_line:
                            return f"❌ Invalid line range: {start_line}-{end_line}. File has {len(lines)} lines."
                        
                        # Extract the specific line range
                        selected_lines = lines[start_line-1:end_line]
                        selected_code = '\n'.join(selected_lines)
                        
                        print(f"🔧 Replacing line range {start_line}-{end_line} ({len(selected_lines)} lines)")
                        print(f"🔍 Selected code preview: {selected_code[:100]}...")
                        
                        # CRITICAL FIX: Use direct line replacement instead of calling _edit_code_with_ai
                        # This avoids the text matching issues that cause extra lines
                        success = self._edit_line_range_with_ai(current_content, selected_code, instruction, current_editor, start_line, end_line)
                        if success:
                            return f"✅ Successfully edited lines {start_line}-{end_line} with AI! The code has been updated in the editor."
                        else:
                            return f"❌ Failed to edit lines {start_line}-{end_line} with AI."
                            
                    except Exception as e:
                        return f"❌ Error processing line range: {str(e)}"
                
                else:
                    # Full file edit - replace entire file content
                    try:
                        # Call AI to edit the entire file
                        success = self._edit_entire_file_with_ai(current_content, instruction, current_editor)
                        if success:
                            return f"✅ Successfully edited entire file with AI! The code has been updated in the editor."
                        else:
                            return f"❌ Failed to edit file with AI."
                    except Exception as e:
                        return f"❌ Error editing entire file: {str(e)}"
            
            else:
                return f"❌ Unknown tool: {tool_name}"
                
        except Exception as e:
            return f"❌ Tool execution error: {str(e)}"
    
    def _open_game_by_name(self, game_name, mode="play"):
        """Open a game by name (helper method for tool-calls)"""
        try:
            print(f"🔧 Tool-call: Opening '{game_name}' in '{mode}' mode")
            
            # Debug: Check main_window reference
            print(f"🔍 Main window reference: {self.main_window}")
            print(f"🔍 Main window type: {type(self.main_window)}")
            if self.main_window:
                print(f"🔍 Main window has game_player: {hasattr(self.main_window, 'game_player')}")
                print(f"🔍 Main window has _open_editor: {hasattr(self.main_window, '_open_editor')}")
                print(f"🔍 Main window has games: {hasattr(self.main_window, 'games')}")
                if hasattr(self.main_window, 'games'):
                    print(f"🔍 Main window has {len(self.main_window.games)} games")
            
            # Use the main_window reference we set up
            if not self.main_window:
                print("❌ Error: Could not find main window (GameBox)")
                return False
            
            print(f"✅ Found main window: {type(self.main_window).__name__}")
            
            # Find the game in GameBox's game list
            found_game = None
            if hasattr(self.main_window, 'games'):
                for game in self.main_window.games:
                    print(f"🔍 Checking game: '{game.name}' vs search: '{game_name}'")
                    if game.name.lower() == game_name.lower():
                        found_game = game
                        print(f"🎯 MATCH FOUND: {found_game.name}")
                        break
            else:
                print("❌ Main window has no 'games' attribute")
                return False
            
            if not found_game:
                print(f"❌ Error: Game '{game_name}' not found in {len(self.main_window.games)} games")
                print(f"Available games: {[g.name for g in self.main_window.games]}")
                return False
            
            print(f"✅ Found game: {found_game.name}")
            print(f"🔍 Game is_valid: {found_game.is_valid()}")
            
            if mode == "play":
                # Simulate the game opening flow without dialog
                print(f"🎮 Opening game in PLAY mode...")
                print(f"🔍 About to call play_game method...")
                
                # Check if game_player exists and has the method
                if hasattr(self.main_window, 'game_player'):
                    print(f"🔍 game_player exists: {self.main_window.game_player}")
                    print(f"🔍 game_player type: {type(self.main_window.game_player)}")
                else:
                    print("❌ game_player not found in main window")
                    return False
                
                found_game.played_times += 1
                found_game.save_manifest()
                
                result = self.main_window.game_player.play_game(found_game)
                print(f"🔍 play_game result: {result}")
                
                if result:
                    print(f"🔍 Calling _disable_top_bar_buttons...")
                    self.main_window._disable_top_bar_buttons()
                    
                    print(f"🔍 Hiding game_list...")
                    self.main_window.game_list.setVisible(False)
                    
                    print(f"🔍 Showing game_player...")
                    self.main_window.game_player.setVisible(True)
                    
                    print(f"✅ Successfully opened game '{found_game.name}' in play mode")
                    return True
                else:
                    print(f"❌ Failed to load game: {found_game.name}")
                    return False
                    
            elif mode == "edit":
                # Open editor directly
                print(f"📝 Opening game in EDITOR mode...")
                print(f"🔍 About to call _open_editor method...")
                
                self.main_window._open_editor(found_game)
                print(f"✅ Successfully called _open_editor for game '{found_game.name}'")
                return True
                
            else:
                print(f"❌ Unknown mode: {mode}")
                return False
            
        except Exception as e:
            print(f"❌ Error opening game '{game_name}': {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _detect_current_context(self):
        """Detect the current tool context for proper tool routing"""
        if not hasattr(self, 'main_window') or not self.main_window:
            return "global"  # Default fallback
        
        # Check if we're in main menu (no game player or editor visible)
        if not self.main_window.game_player.isVisible() and not hasattr(self.main_window, 'current_editor'):
            return "main_menu"
        
        # Check if we're in gameplay mode (game player visible, instant editor may be active)
        if self.main_window.game_player.isVisible():
            return "gameplay"
        
        # Check if we're in editor mode (main editor window)
        if hasattr(self.main_window, 'current_editor') and self.main_window.current_editor:
            return "editor"
        
        return "global"
    
    def _get_available_tools_for_context(self, context):
        """Get available tools for the current context"""
        # Define tool categories
        categories = {
            "main_menu": [
                "play_game_name",
                "edit_game_name",
                "get_tools"
            ],
            "gameplay": [
                "edit_selected",
                "edit_code"
            ],
            "editor": [
                "edit_selected", 
                "edit_code"
            ],
            "global": [
                "get_tools"
            ]
        }
        
        # For gameplay and editor, they should have global tools too
        available = categories.get(context, categories["global"]).copy()
        if context in ["gameplay", "editor"]:
            available.extend(categories["global"])
        
        return available
    
    def _edit_code_with_ai(self, selected_code, instruction, editor_widget=None):
        """Edit selected code using AI and apply it to the current editor"""
        try:
            print(f"🔧 AI Tool-call: Editing selected code with instruction: {instruction}")
            
            # Get full file context
            current_content = ""
            current_editor = editor_widget
            
            # If no editor_widget provided, try to determine the current editor
            if not current_editor and hasattr(self, 'main_window') and self.main_window:
                # Check if we're in editor mode
                if hasattr(self.main_window, 'game_player') and self.main_window.game_player.isVisible():
                    # We're in game player (might have live editor)
                    current_editor = self.main_window.game_player.live_code_editor
                    if current_editor:
                        current_content = current_editor.toPlainText()
                elif hasattr(self.main_window, 'current_editor') and self.main_window.current_editor:
                    # We're in main game editor
                    current_editor = self.main_window.current_editor.code_editor
                    if current_editor:
                        current_content = current_editor.toPlainText()
            
            # If we have an editor widget but no content, get the content
            if current_editor and not current_content:
                current_content = current_editor.toPlainText()
            
            if not current_content:
                print("❌ Error: Could not get current file content")
                return False
            
            # Create AI prompt for code editing
            prompt = f"""You are an expert HTML/CSS/JavaScript developer. I need you to edit specific selected code based on user instructions.

USER INSTRUCTION: {instruction}

SELECTED CODE TO EDIT:
```html
{selected_code}
```

FULL FILE CONTEXT:
```html
{current_content}
```

TASK:
1. Analyze the selected code in the context of the full file
2. Apply the user's instructions to modify/improve the selected code
3. ⚠️ CRITICAL: Return the COMPLETE selected code with your modifications integrated
4. ⚠️ DO NOT return only the changed parts - return the ENTIRE selected code block
5. ⚠️ If your instruction only affects part of the code, keep ALL other parts unchanged
6. Ensure the edited code maintains proper syntax and formatting
7. Keep the code functional and integrate well with the surrounding code

MODE DETECTION:
- If the instruction requires modifying code OUTSIDE the selected area, suggest using 'Edit Code' mode instead
- If the instruction is too broad for the selected code, suggest using 'Edit Code' mode
- Examples that need Edit Code mode: "add a new function", "change the page layout", "add new sections"

CRITICAL SPACING PRESERVATION INSTRUCTION:
- For HTML content: ALWAYS prefix the FIRST line of your response with "<!--.-->"
- For CSS content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- For JavaScript content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- This invisible comment is essential for preserving leading spaces during copy/paste
- Example: If your HTML response starts with "    <div class='test'>", write "<!--.-->     <div class='test'>"
- The comment will be invisible but ensures all leading spaces are preserved

RESPONSE FORMAT:
- Return ONLY the complete edited selected code
- Do not include explanations, line numbers, or additional text
- Do not include "Here is the modified code:" or similar prefixes"""
            
            # Call AI to process the request
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                print("❌ Error: AI model not available")
                return False
            
            # Show which model is being used
            print(f"🤖 Using {model_name} for AI code editing...")
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                ai_response = response.text.strip()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name}, switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        print("❌ Error: Failed to switch to backup model")
                        return False
                    
                    print(f"🤖 Switched to {backup_model_name} for AI code editing...")
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    ai_response = response.text.strip()
                else:
                    # Re-raise if it's not a rate limit error
                    raise rate_limit_error
            
            if not ai_response:
                print("❌ Error: AI returned empty response")
                return False
            
            # Extract content from markdown code blocks if present
            extracted_content = extract_content_from_code_blocks(ai_response)
            print(f"🔧 Extracted content from AI response (length: {len(extracted_content)})")
            
            # PRESERVE ALL COMMENTS: Keep all content including AI spacing markers for correct pasting
            # The AI adds /*.*/ and <!--.--> markers to preserve formatting - these must be copied as-is
            print(f"🔧 Full AI content will be preserved (length: {len(extracted_content)})")
            
            # Get the current text cursor to find and replace the selected text
            if current_editor:
                print(f"🔧 Attempting to replace text. Current editor type: {type(current_editor).__name__}")
                
                # Find the exact position where selected code appears
                full_text = current_editor.toPlainText()
                print(f"🔍 Full text length: {len(full_text)}, Selected code length: {len(selected_code)}")
                
                # Try multiple approaches to find the selected code
                selected_start_index = -1
                
                # Method 1: Direct string matching with better validation
                selected_start_index = full_text.find(selected_code)
                
                # Method 1.5: Handle AI prefix markers - if direct match fails, try removing AI markers
                if selected_start_index == -1:
                    # Check if the extracted content has AI prefix markers
                    if extracted_content.startswith('/*.*/'):
                        # AI added JavaScript spacing marker - find the code after it
                        ai_code_content = extracted_content[5:].lstrip()
                        selected_start_index = full_text.find(selected_code)
                        if selected_start_index != -1:
                            # Found the selected code, will replace with full AI content (including marker)
                            print(f"🔧 AI JavaScript marker detected, preserving /*.*/ in replacement")
                    elif extracted_content.startswith('<!--.-->'):
                        # AI added HTML spacing marker - find the code after it
                        ai_code_content = extracted_content[8:].lstrip()
                        selected_start_index = full_text.find(selected_code)
                        if selected_start_index != -1:
                            # Found the selected code, will replace with full AI content (including marker)
                            print(f"🔧 AI HTML marker detected, preserving <!--.--> in replacement")
                if selected_start_index != -1:
                    # Validate this is the correct match by checking context around it
                    # This prevents finding partial matches within comments or strings
                    context_start = max(0, selected_start_index - 50)
                    context_end = min(len(full_text), selected_start_index + len(selected_code) + 50)
                    context = full_text[context_start:context_end]
                    
                    # If the match looks suspicious (multiple occurrences), try to find the best one
                    if selected_code in full_text[selected_start_index + 1:]:
                        # Found multiple occurrences - try to find the most recent one near cursor position
                        if hasattr(current_editor, 'textCursor'):
                            cursor_pos = current_editor.textCursor().position()
                            all_occurrences = []
                            start_pos = 0
                            while True:
                                pos = full_text.find(selected_code, start_pos)
                                if pos == -1:
                                    break
                                all_occurrences.append(pos)
                                start_pos = pos + 1
                            
                            # Find the occurrence closest to cursor position
                            best_match = min(all_occurrences, key=lambda x: abs(x - cursor_pos))
                            selected_start_index = best_match
                            print(f"🔍 Found multiple matches, selected closest to cursor (position {best_match})")
                
                if selected_start_index == -1:
                    # Method 2: Try with normalized whitespace as fallback
                    selected_normalized = ' '.join(selected_code.split())
                    full_normalized = ' '.join(full_text.split())
                    selected_start_index = full_normalized.find(selected_normalized)
                    if selected_start_index == -1:
                        # Method 3: If still not found, try replacing entire file content
                        print("⚠️ Text not found in current position, attempting full content replacement...")
                        # This fallback handles cases where selection might be lost
                        # DO NOT STRIP: Comment prefixes like /*.*/ and <!--.--> must be preserved
                        # extracted_content = extracted_content.strip()  # REMOVED - preserves comment prefixes
                        if extracted_content:
                            cursor = current_editor.textCursor()
                            cursor.beginEditBlock()
                            cursor.select(cursor.Document)
                            cursor.removeSelectedText()
                            cursor.insertText(extracted_content)
                            cursor.endEditBlock()
                            
                            # Force immediate text change event
                            if hasattr(current_editor, 'parent') and hasattr(current_editor.parent(), '_on_live_text_changed'):
                                current_editor.parent()._on_live_text_changed()
                                print("🔄 Triggered live editor text change event (fallback method)")
                            elif hasattr(current_editor, 'parent') and hasattr(current_editor.parent(), '_on_text_changed'):
                                current_editor.parent()._on_text_changed()
                                print("🔄 Triggered main editor text change event (fallback method)")
                            
                            return True
                
                if selected_start_index != -1:
                    # Replace ONLY the selected text with AI's result, preserving everything else
                    selected_end_index = selected_start_index + len(selected_code)
                    
                    # Debug: Show what we're about to replace
                    original_section = full_text[selected_start_index:selected_end_index]
                    print(f"🔍 Original section to replace (first 100 chars): {repr(original_section[:100])}")
                    print(f"🔍 AI replacement content (first 100 chars): {repr(extracted_content[:100])}")
                    
                    # Show comment/prefix marker preservation info
                    if extracted_content.startswith('/*.*/') or extracted_content.startswith('<!--.-->'):
                        print(f"✅ Comments and markers preserved in replacement - copier will copy them as-is")
                    
                    print(f"🔧 Replacing text from position {selected_start_index} to {selected_end_index} (length: {len(selected_code)} -> {len(extracted_content)})")
                    
                    # Position cursor at the exact location and replace only the selected text
                    cursor = current_editor.textCursor()
                    cursor.beginEditBlock()
                    
                    # Position cursor at start of selected text
                    cursor.setPosition(selected_start_index)
                    cursor.setPosition(selected_end_index, cursor.KeepAnchor)
                    
                    # Replace only the selected text with AI's result
                    cursor.removeSelectedText()
                    cursor.insertText(extracted_content)
                    
                    cursor.endEditBlock()
                    
                    print(f"✅ Successfully replaced selected code with AI result (length: {len(new_text)})")
                    
                    # Force immediate text change event
                    if hasattr(current_editor, 'parent') and hasattr(current_editor.parent(), '_on_live_text_changed'):
                        # This is the live editor
                        current_editor.parent()._on_live_text_changed()
                        print("🔄 Triggered live editor text change event")
                    elif hasattr(current_editor, 'parent') and hasattr(current_editor.parent(), '_on_text_changed'):
                        # This is the main editor
                        current_editor.parent()._on_text_changed()
                        print("🔄 Triggered main editor text change event")
                    
                    return True
                else:
                    print("❌ Error: Could not find selected text in current editor")
                    print(f"Selected code preview: {selected_code[:100]}...")
                    print(f"Full text preview: {full_text[:200]}...")
                    return False
            else:
                print("❌ Error: Could not determine current editor")
                return False
                
        except Exception as e:
            print(f"❌ Error editing code with AI: {e}")
            import traceback
            traceback.print_exc()
            return False


    def _edit_line_range_with_ai(self, full_content, selected_code, instruction, editor_widget, start_line, end_line):
        """Edit specific line range with AI - more precise than _edit_code_with_ai"""
        try:
            print(f"🔧 AI Line Range Edit: Lines {start_line}-{end_line}, Instruction: {instruction}")
            
            if not selected_code:
                print("❌ Error: No selected code to edit")
                return False
                
            if not instruction:
                print("❌ Error: No instruction provided")
                return False
            
            # Create AI prompt for line range editing
            prompt = f"""You are an expert HTML/CSS/JavaScript developer. I need you to edit specific selected code based on user instructions.

USER INSTRUCTION: {instruction}

SELECTED CODE TO EDIT (lines {start_line}-{end_line}):
```html
{selected_code}
```

FULL FILE CONTEXT:
```html
{full_content}
```

TASK:
1. Apply the user's instructions to modify ONLY the selected code
2. ⚠️ CRITICAL: Return the COMPLETE selected lines with your modifications integrated
3. ⚠️ DO NOT return only the changed parts - return ALL the selected lines
4. Ensure the edited lines maintain proper syntax and formatting
5. Keep the code functional and integrate well with surrounding lines

IMPORTANT: Return exactly {len(selected_code.split('\n'))} lines to maintain the same line count.

CRITICAL SPACING PRESERVATION INSTRUCTION:
- For HTML content: ALWAYS prefix the FIRST line of your response with "<!--.-->"
- For CSS content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- For JavaScript content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- This invisible comment is essential for preserving leading spaces during copy/paste
- Example: If your HTML response starts with "    <div>", write "<!--.-->    <div>"
- The comment will be invisible but ensures all leading spaces are preserved

RESPONSE FORMAT:
- Return ONLY the complete edited selected lines
- Do not include explanations, line numbers, or additional text
- Do not include "Here is the modified code:" or similar prefixes"""
            
            # Call AI to process the request
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                print("❌ Error: AI model not available")
                return False
            
            # Show which model is being used
            print(f"🤖 Using {model_name} for AI line range editing...")
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                ai_response = response.text.strip()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name}, switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        print("❌ Error: Failed to switch to backup model")
                        return False
                    
                    print(f"🤖 Switched to {backup_model_name} for AI line range editing...")
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    ai_response = response.text.strip()
                else:
                    # Re-raise other exceptions
                    raise rate_limit_error
            
            if not ai_response:
                print("❌ Error: AI returned empty response")
                return False
            
            # Extract content from markdown code blocks if present
            from . import extract_content_from_code_blocks
            extracted_content = extract_content_from_code_blocks(ai_response)
            print(f"🔧 Extracted line range content from AI response (length: {len(extracted_content)})")
            print(f"🔍 DEBUG: Line range - AI response preview: {repr(ai_response[:100])}")
            print(f"🔍 DEBUG: Line range - Extracted content preview: {repr(extracted_content[:100])}")
            
            # PRESERVE ALL COMMENTS: Keep all content including AI spacing markers for correct pasting
            print(f"🔧 Full AI content will be preserved (length: {len(extracted_content)})")
            
            # Get the current text cursor to find and replace the selected line range
            if editor_widget:
                try:
                    full_text = editor_widget.toPlainText()
                    print(f"🔍 Full text length: {len(full_text)}, Selected code length: {len(selected_code)}")
                    
                    # Calculate exact positions for line range replacement
                    lines = full_text.split('\n')
                    total_lines = len(lines)
                    
                    # Find start position of line range
                    start_pos = 0
                    for i in range(start_line - 1):
                        start_pos += len(lines[i]) + 1  # +1 for newline character
                    
                    # Find end position of line range
                    end_pos = start_pos
                    for i in range(start_line - 1, end_line):
                        end_pos += len(lines[i])
                        if i < end_line - 1:
                            end_pos += 1  # +1 for newline character
                    
                    print(f"🔧 Replacing line range from position {start_pos} to {end_pos}")
                    print(f"🔧 Original range ({start_line}-{end_line}): {repr(full_text[start_pos:end_pos][:100])}")
                    print(f"🔧 AI replacement content: {repr(extracted_content[:100])}")
                    
                    # Replace only the selected line range with AI's result
                    cursor = editor_widget.textCursor()
                    cursor.beginEditBlock()
                    
                    # Position cursor at start and select the exact range
                    cursor.setPosition(start_pos)
                    cursor.setPosition(end_pos, cursor.KeepAnchor)
                    
                    # Replace only the selected line range
                    cursor.removeSelectedText()
                    cursor.insertText(extracted_content)
                    
                    cursor.endEditBlock()
                    
                    print(f"✅ Successfully replaced line range {start_line}-{end_line} with AI result")
                    
                    # Force immediate text change event
                    if hasattr(editor_widget, 'parent') and hasattr(editor_widget.parent(), '_on_live_text_changed'):
                        # This is the live editor
                        editor_widget.parent()._on_live_text_changed()
                        print("🔄 Triggered live editor text change event")
                    elif hasattr(editor_widget, 'parent') and hasattr(editor_widget.parent(), '_on_text_changed'):
                        # This is the main editor
                        editor_widget.parent()._on_text_changed()
                        print("🔄 Triggered main editor text change event")
                    
                    return True
                except Exception as e:
                    print(f"❌ Error replacing line range: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            else:
                print("❌ Error: No editor widget provided")
                return False
                
        except Exception as e:
            print(f"❌ Error editing line range with AI: {e}")
            import traceback
            traceback.print_exc()
            return False


    def _edit_entire_file_with_ai(self, current_content, instruction, editor_widget):
        """Edit entire file content using AI - for edit_code full file mode"""
        try:
            print(f"🔧 AI Full File Edit: Instruction: {instruction}")
            
            if not current_content:
                print("❌ Error: No current content to edit")
                return False
                
            if not instruction:
                print("❌ Error: No instruction provided")
                return False
            
            # Create AI prompt for full file editing
            prompt = f"""You are an expert HTML/CSS/JavaScript developer. I need you to edit an entire file based on user instructions.

USER INSTRUCTION: {instruction}

FULL FILE CONTENT TO EDIT:
```html
{current_content}
```

TASK:
1. Apply the user's instructions to modify the file as requested
2. ⚠️ CRITICAL: Return the COMPLETE file with your modifications integrated
3. ⚠️ DO NOT return only the changed parts - return the ENTIRE file
4. Ensure the edited file maintains proper syntax and formatting
5. Keep the code functional and well-structured
6. Preserve all existing code that should not be changed

CRITICAL SPACING PRESERVATION INSTRUCTION:
- For HTML content: ALWAYS prefix the FIRST line of your response with "<!--.-->"
- For CSS content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- For JavaScript content: ALWAYS prefix the FIRST line of your response with "/*.*/"
- This invisible comment is essential for preserving leading spaces during copy/paste
- Example: If your HTML response starts with "    <html>", write "<!--.-->    <html>"
- The comment will be invisible but ensures all leading spaces are preserved

RESPONSE FORMAT:
- Return ONLY the complete edited file content
- Do not include explanations, line numbers, or additional text
- Do not include "Here is the modified code:" or similar prefixes"""
            
            # Call AI to process the request
            ai_model, model_name = create_gamai_model()
            if not ai_model:
                print("❌ Error: AI model not available")
                return False
            
            # Show which model is being used
            print(f"🤖 Using {model_name} for AI full file editing...")
            
            # Generate AI response with fallback capability
            try:
                response = ai_model.generate_content(prompt)
                ai_response = response.text.strip()
            except Exception as rate_limit_error:
                # Check if it's a rate limit error and try backup model
                error_msg = str(rate_limit_error).lower()
                if "rate limit" in error_msg or "quota" in error_msg or "limit" in error_msg:
                    print(f"🔄 Rate limit reached on {model_name}, switching to backup model...")
                    # Switch to backup model
                    ai_model, backup_model_name = switch_to_backup_model(model_name)
                    if not ai_model:
                        print("❌ Error: Failed to switch to backup model")
                        return False
                    
                    print(f"🤖 Switched to {backup_model_name} for AI full file editing...")
                    
                    # Try again with backup model
                    response = ai_model.generate_content(prompt)
                    ai_response = response.text.strip()
                else:
                    # Re-raise other exceptions
                    raise rate_limit_error
            
            if not ai_response:
                print("❌ Error: AI returned empty response")
                return False
            
            # Extract content from markdown code blocks if present
            from . import extract_content_from_code_blocks
            extracted_content = extract_content_from_code_blocks(ai_response)
            print(f"🔧 Extracted full file content from AI response (length: {len(extracted_content)})")
            print(f"🔍 DEBUG: Full file - AI response preview: {repr(ai_response[:100])}")
            print(f"🔍 DEBUG: Full file - Extracted content preview: {repr(extracted_content[:100])}")
            
            # PRESERVE ALL COMMENTS: Keep all content including AI spacing markers for correct pasting
            # The AI adds /*.*/ and <!--.--> markers to preserve formatting - these must be copied as-is
            print(f"🔧 Full AI content will be preserved (length: {len(extracted_content)})")
            
            # Replace the entire file content with AI's result
            if editor_widget:
                try:
                    # Replace entire document content
                    cursor = editor_widget.textCursor()
                    cursor.beginEditBlock()
                    
                    # Select entire document
                    cursor.select(cursor.Document)
                    cursor.removeSelectedText()
                    cursor.insertText(extracted_content)
                    
                    cursor.endEditBlock()
                    
                    print(f"✅ Successfully replaced entire file with AI result (length: {len(current_content)} -> {len(extracted_content)})")
                    
                    # Force immediate text change event
                    if hasattr(editor_widget, 'parent') and hasattr(editor_widget.parent(), '_on_live_text_changed'):
                        # This is the live editor
                        editor_widget.parent()._on_live_text_changed()
                        print("🔄 Triggered live editor text change event")
                    elif hasattr(editor_widget, 'parent') and hasattr(editor_widget.parent(), '_on_text_changed'):
                        # This is the main editor
                        editor_widget.parent()._on_text_changed()
                        print("🔄 Triggered main editor text change event")
                    
                    return True
                except Exception as e:
                    print(f"❌ Error replacing file content: {e}")
                    import traceback
                    traceback.print_exc()
                    return False
            else:
                print("❌ Error: No editor widget provided")
                return False
                
        except Exception as e:
            print(f"❌ Error editing entire file with AI: {e}")
            import traceback
            traceback.print_exc()
            return False


class RatingDialog(QDialog):
    """Dialog for rating games with 1/5 stars and arrow navigation"""
    
    def __init__(self, current_rating, game_name, parent=None):
        super().__init__(parent)
        self.current_rating = current_rating  # None for unrated, 1-5 for rated
        self.game_name = game_name
        self.selected_rating = current_rating  # Track current selection
        self.setWindowTitle(f"Rate Game - {game_name}")
        self.setFixedSize(600, 550)  # Increased from 520x360 to 600x550 for better content display and spacing
        self.setModal(True)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup the rating dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)  # Optimized from 15px for better space efficiency with larger dialog
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Title
        title_label = QLabel(f"🎮 Rate: {self.game_name}")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold; margin-bottom: 20px;")
        layout.addWidget(title_label)
        
        # Current rating display
        self._create_rating_display(layout)
        
        # Rating navigation
        self._create_rating_navigation(layout)
        
        # Action buttons
        self._create_action_buttons(layout)
        
        # Set dialog background
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
            QCheckBox {
                color: white;
                font-size: 13px;
            }
        """)  # Search dialog pattern styling
    
    def _create_rating_display(self, layout):
        """Create rating display section"""
        display_group = QGroupBox("Current Rating")
        display_group.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: #E5E5E5;
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                background-color: #1a1a1a;
                color: #E5E5E5;
            }
        """)
        
        display_layout = QVBoxLayout(display_group)
        
        # Stars display
        self.stars_display = QLabel()
        self._update_stars_display()
        self.stars_display.setAlignment(Qt.AlignCenter)
        self.stars_display.setStyleSheet("font-size: 36px; font-weight: bold; color: #E5E5E5; margin: 10px 0;")
        display_layout.addWidget(self.stars_display)
        
        # Rating text
        self.rating_text = QLabel()
        self._update_rating_text()
        self.rating_text.setAlignment(Qt.AlignCenter)
        self.rating_text.setStyleSheet("color: #CCC; font-size: 14px;")
        display_layout.addWidget(self.rating_text)
        
        layout.addWidget(display_group)
    
    def _create_rating_navigation(self, layout):
        """Create rating navigation with arrows and star buttons"""
        nav_group = QGroupBox("Select Rating")
        nav_group.setStyleSheet("""
            QGroupBox {
                font-size: 16px;
                font-weight: bold;
                color: white;  /* Consistent label styling - was green */
                border: 2px solid #555;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                background-color: #1a1a1a;
                color: white;  /* Consistent label styling - was green */
            }
        """)
        
        nav_layout = QVBoxLayout(nav_group)
        nav_layout.setSpacing(15)
        
        # Star buttons row
        stars_layout = QHBoxLayout()
        stars_layout.setSpacing(10)
        
        self.star_buttons = []
        for i in range(1, 6):
            star_btn = QPushButton(f"{i} ⭐")
            star_btn.setFixedSize(70, 70)
            star_btn.setCursor(Qt.PointingHandCursor)
            star_btn.clicked.connect(lambda checked, r=i: self._select_rating(r))
            star_btn.setStyleSheet("""
                QPushButton {
                    background-color: #333;
                    color: #E5E5E5;
                    border: 2px solid #555;
                    border-radius: 8px;
                    font-size: 13px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #444;
                    border-color: #666;
                }
                QPushButton:pressed {
                    background-color: #222;
                    border-color: #E5E5E5;
                }
            """)
            self.star_buttons.append(star_btn)
            stars_layout.addWidget(star_btn)
        
        nav_layout.addLayout(stars_layout)
        
        # Arrow navigation buttons
        arrow_layout = QHBoxLayout()
        arrow_layout.setSpacing(20)
        
        # Left arrow
        left_arrow = QPushButton("◀ Previous")
        left_arrow.setFixedSize(120, 45)
        left_arrow.setCursor(Qt.PointingHandCursor)
        left_arrow.clicked.connect(self._previous_rating)
        left_arrow.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        arrow_layout.addWidget(left_arrow)
        
        # Right arrow
        right_arrow = QPushButton("Next ▶")
        right_arrow.setFixedSize(120, 45)
        right_arrow.setCursor(Qt.PointingHandCursor)
        right_arrow.clicked.connect(self._next_rating)
        right_arrow.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        arrow_layout.addWidget(right_arrow)
        
        nav_layout.addLayout(arrow_layout)
        layout.addWidget(nav_group)
    
    def _create_action_buttons(self, layout):
        """Create OK and Cancel buttons"""
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)
        
        # Cancel button
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedSize(140, 45)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        button_layout.addWidget(cancel_btn)
        
        # OK button
        ok_btn = QPushButton("OK - Save Rating")
        ok_btn.setFixedSize(160, 45)
        ok_btn.setCursor(Qt.PointingHandCursor)
        ok_btn.clicked.connect(self._save_rating)
        ok_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
        """)
        button_layout.addWidget(ok_btn)
        
        layout.addLayout(button_layout)
    
    def _update_stars_display(self):
        """Update the stars display"""
        if self.selected_rating is None:
            stars_text = "☆☆☆☆☆"
            self.stars_display.setStyleSheet("font-size: 36px; font-weight: bold; color: #666; margin: 10px 0;")
        else:
            stars_text = "★" * self.selected_rating + "☆" * (5 - self.selected_rating)
            self.stars_display.setStyleSheet("font-size: 36px; font-weight: bold; color: #E5E5E5; margin: 10px 0;")
        self.stars_display.setText(stars_text)
    
    def _update_rating_text(self):
        """Update the rating text"""
        if self.selected_rating is None:
            self.rating_text.setText("Not rated")
            self.rating_text.setStyleSheet("color: #888; font-size: 14px;")
        else:
            self.rating_text.setText(f"{self.selected_rating}/5 Stars")
            self.rating_text.setStyleSheet("color: #E5E5E5; font-size: 14px; font-weight: bold;")
    
    def _select_rating(self, rating):
        """Select a rating (1-5 or None for unrated)"""
        self.selected_rating = rating if rating != 0 else None
        self._update_stars_display()
        self._update_rating_text()
    
    def _previous_rating(self):
        """Navigate to previous rating"""
        if self.selected_rating is None:
            new_rating = 5
        elif self.selected_rating > 1:
            new_rating = self.selected_rating - 1
        else:
            new_rating = None  # Wrap around to unrated
        self._select_rating(new_rating)
    
    def _next_rating(self):
        """Navigate to next rating"""
        if self.selected_rating is None:
            new_rating = 1
        elif self.selected_rating < 5:
            new_rating = self.selected_rating + 1
        else:
            new_rating = None  # Wrap around to unrated
        self._select_rating(new_rating)
    
    def _save_rating(self):
        """Save rating and close dialog"""
        # Validate rating before accepting
        if self.selected_rating is not None and not (1 <= self.selected_rating <= 5):
            QMessageBox.warning(self, "Invalid Rating", "Rating must be between 1 and 5 stars.")
            return
        
        self.accept()
    
    def get_selected_rating(self):
        """Get the selected rating"""
        return self.selected_rating


class ManifestEditorDialog(QDialog):
    """Powerful manifest editor dialog for editing game properties in the editor"""
    
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setWindowTitle(f"Manifest Editor - {game.name}")
        self.setFixedSize(800, 800)  # Fixed size for scrollable content area
        self.setModal(True)
        self._setup_ui()
        self._populate_existing_values()
    
    def _setup_ui(self):
        # Main layout with scroll area for unlimited content
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)  # No spacing for clean scroll area
        main_layout.setContentsMargins(0, 0, 0, 0)  # No margins for full scroll width
        
        # Create scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Only vertical scroll
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #1a1a1a;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #E5E5E5;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #E5E5E5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        # Content widget inside scroll area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(25)  # Better spacing between sections
        content_layout.setContentsMargins(40, 30, 40, 30)  # Clean margins for content
        
        # Title
        title_label = QLabel("Manifest Editor")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 28px; font-weight: bold; color: white; margin: 10px 0 25px 0;")
        content_layout.addWidget(title_label)
        
        # Basic Properties Section
        basic_layout = QVBoxLayout()
        basic_label = QLabel("Basic Properties")
        basic_label.setStyleSheet("color: #E5E5E5; font-size: 20px; font-weight: bold; margin-bottom: 18px;")
        basic_layout.addWidget(basic_label)
        
        # Name input
        name_layout = QVBoxLayout()
        name_label = QLabel("Game Name:")
        name_label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 10px;")
        self.name_input = QLineEdit()
        self.name_input.setMinimumHeight(50)  # Comfortable height for text
        self.name_input.setPlaceholderText("Enter game name...")
        self.name_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 15px;
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
        """)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_input)
        basic_layout.addLayout(name_layout)
        
        # Add spacing between name and version
        basic_layout.addSpacing(16)
        
        # Version input
        version_layout = QVBoxLayout()
        version_label = QLabel("Version:")
        version_label.setStyleSheet("color: white; font-size: 16px; margin-bottom: 10px;")
        self.version_input = QLineEdit()
        self.version_input.setMinimumHeight(50)  # Comfortable height for text
        self.version_input.setPlaceholderText("Enter version (e.g., 1.0.0)")
        self.version_input.setStyleSheet("""
            QLineEdit {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 15px;
                color: white;
                font-size: 16px;
                selection-background-color: #E5E5E5;
            }
            QLineEdit:focus {
                border-color: #E5E5E5;
                background-color: #333333;
            }
        """)
        version_layout.addWidget(version_label)
        version_layout.addWidget(self.version_input)
        basic_layout.addLayout(version_layout)
        
        content_layout.addLayout(basic_layout)
        
        # Add spacing after basic properties
        content_layout.addSpacing(20)
        
        # Game Metadata Section
        metadata_layout = QGridLayout()
        metadata_label = QLabel("Game Metadata")
        metadata_label.setStyleSheet("color: #E5E5E5; font-size: 20px; font-weight: bold; margin: 20px 0 18px 0;")
        content_layout.addWidget(metadata_label)
        metadata_layout.setSpacing(18)
        
        # Type field
        type_label = QLabel("Type:")
        type_label.setStyleSheet("color: white; font-size: 14px;")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["2D", "3D"])
        self.type_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 6px;
                padding: 10px;
                color: white;
                font-size: 14px;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
            }
            QComboBox::drop-down {
                border: none;
                width: 25px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid white;
                margin-right: 3px;
            }
        """)
        
        # Players field
        players_label = QLabel("Players:")
        players_label.setStyleSheet("color: white; font-size: 16px;")
        self.players_combo = QComboBox()
        self.players_combo.addItems(["1", "2"])
        self.players_combo.setStyleSheet("""
            QComboBox {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                padding: 12px;
                color: white;
                font-size: 15px;
            }
            QComboBox:focus {
                border-color: #E5E5E5;
            }
            QComboBox::drop-down {
                border: none;
                width: 25px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 4px solid white;
                margin-right: 3px;
            }
        """)
        
        metadata_layout.addWidget(type_label, 0, 0)
        metadata_layout.addWidget(self.type_combo, 0, 1)
        metadata_layout.addWidget(players_label, 1, 0)
        metadata_layout.addWidget(self.players_combo, 1, 1)
        content_layout.addLayout(metadata_layout)
        
        # Add spacing before categories
        content_layout.addSpacing(20)
        

        # Categories Section
        categories_label = QLabel("Categories")
        categories_label.setStyleSheet("color: #E5E5E5; font-size: 20px; font-weight: bold; margin: 25px 0 20px 0;")
        content_layout.addWidget(categories_label)
        
        # Main Categories
        main_cat_group = QGroupBox("Main Categories (Max 5)")
        main_cat_group.setStyleSheet("""
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                color: white;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px 0 8px;
                background-color: #1a1a1a;
                color: white;
            }
        """)
        
        main_cat_layout = QVBoxLayout(main_cat_group)
        main_cat_layout.setSpacing(12)
        
        self.main_categories_list = QListWidget()
        # No height restriction - let it grow naturally with scroll content
        self.main_categories_list.setMinimumHeight(200)  # Comfortable starting height
        self.main_categories_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                color: white;
                font-size: 14px;
                padding: 10px;
            }
            QListWidget:focus {
                border-color: #E5E5E5;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3a3a3a;
                /* Ensure at least one line is visible */
            }
            QListWidget::item:last {
                border-bottom: none;
            }
            QListWidget::item:selected {
                background-color: #E5E5E5;
            }
        """)
        
        # Populate main categories
        for category in MAIN_CATEGORIES:
            item = QListWidgetItem(category)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.main_categories_list.addItem(item)
        
        self.main_cat_count_label = QLabel("Selected: 0/5")
        self.main_cat_count_label.setStyleSheet("color: #888; font-size: 13px; margin-top: 8px;")
        
        main_cat_layout.addWidget(self.main_categories_list)
        main_cat_layout.addWidget(self.main_cat_count_label)
        content_layout.addWidget(main_cat_group)
        
        # Sub Categories
        sub_cat_group = QGroupBox("Sub Categories (Unlimited)")
        sub_cat_group.setStyleSheet("""
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                color: white;
                border: 2px solid #3a3a3a;
                border-radius: 8px;
                margin-top: 18px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px 0 8px;
                background-color: #1a1a1a;
                color: white;
            }
        """)
        
        sub_cat_layout = QVBoxLayout(sub_cat_group)
        sub_cat_layout.setSpacing(12)
        
        self.sub_categories_list = QListWidget()
        # No height restriction - let it grow naturally with scroll content
        self.sub_categories_list.setMinimumHeight(250)  # Comfortable starting height
        self.sub_categories_list.setStyleSheet("""
            QListWidget {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 6px;
                color: white;
                font-size: 14px;
                padding: 10px;
            }
            QListWidget:focus {
                border-color: #E5E5E5;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3a3a3a;
                /* Ensure at least one line is visible */
            }
            QListWidget::item:last {
                border-bottom: none;
            }
            QListWidget::item:selected {
                background-color: #E5E5E5;
            }
        """)
        
        # Populate sub categories
        for category in SUB_CATEGORIES:
            item = QListWidgetItem(category)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.sub_categories_list.addItem(item)
        
        self.sub_cat_count_label = QLabel("Selected: 0")
        self.sub_cat_count_label.setStyleSheet("color: #888; font-size: 13px; margin-top: 8px;")
        
        sub_cat_layout.addWidget(self.sub_categories_list)
        sub_cat_layout.addWidget(self.sub_cat_count_label)
        content_layout.addWidget(sub_cat_group)
        
        # Add spacing before buttons
        content_layout.addSpacing(25)
        
        # Buttons Section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(18)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(130, 45)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        
        save_button = QPushButton("Save Changes")
        save_button.setFixedSize(160, 45)
        save_button.setCursor(Qt.PointingHandCursor)
        save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 15px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        save_button.clicked.connect(self._save_changes)
        
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        content_layout.addLayout(button_layout)
        
        # Add final spacing
        content_layout.addSpacing(20)
        
        # Set up scroll area
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)
        
        # Background styling
        self.setStyleSheet("background-color: #1a1a1a;")
        
        # Connect signals
        self.main_categories_list.itemChanged.connect(self._handle_main_category_change)
        self.sub_categories_list.itemChanged.connect(self._handle_sub_category_change)
    
    def _populate_existing_values(self):
        """Populate form with existing game values"""
        # Basic properties
        self.name_input.setText(self.game.name)
        self.version_input.setText(self.game.version)
        self.type_combo.setCurrentText(self.game.type)
        self.players_combo.setCurrentText(self.game.players)
        

        # Categories - handle null values
        main_cats = self.game.main_categories or ["null", "null", "null"]
        sub_cats = self.game.sub_categories or ["null", "null", "null"]
        
        # Set main categories (exclude null values)
        main_selected = 0
        for i in range(self.main_categories_list.count()):
            item = self.main_categories_list.item(i)
            category_name = item.text()
            if category_name in main_cats and category_name != "null":
                item.setCheckState(Qt.Checked)
                main_selected += 1
        
        # Set sub categories (exclude null values)
        sub_selected = 0
        for i in range(self.sub_categories_list.count()):
            item = self.sub_categories_list.item(i)
            category_name = item.text()
            if category_name in sub_cats and category_name != "null":
                item.setCheckState(Qt.Checked)
                sub_selected += 1
        
        # Update count labels
        self.main_cat_count_label.setText(f"Selected: {main_selected}/5")
        self.sub_cat_count_label.setText(f"Selected: {sub_selected}")
    

    def _handle_main_category_change(self, item):
        """Handle main category selection changes with 5-limit enforcement"""
        if item.checkState() == Qt.Checked:
            # Count current selections
            current_count = 0
            for i in range(self.main_categories_list.count()):
                if self.main_categories_list.item(i).checkState() == Qt.Checked:
                    current_count += 1
            
            # If exceeding limit, uncheck the item
            if current_count > 5:
                item.setCheckState(Qt.Unchecked)
                # Show warning
                QMessageBox.warning(self, "Limit Exceeded", 
                                  "Maximum 5 main categories allowed!")
        
        # Update count display
        count = 0
        for i in range(self.main_categories_list.count()):
            if self.main_categories_list.item(i).checkState() == Qt.Checked:
                count += 1
        self.main_cat_count_label.setText(f"Selected: {count}/5")
    
    def _handle_sub_category_change(self, item):
        """Handle sub category selection changes"""
        # Update count display
        count = 0
        for i in range(self.sub_categories_list.count()):
            if self.sub_categories_list.item(i).checkState() == Qt.Checked:
                count += 1
        self.sub_cat_count_label.setText(f"Selected: {count}")
    
    def _save_changes(self):
        """Save all changes to the game manifest"""
        # Validate basic inputs
        name = self.name_input.text().strip()
        version = self.version_input.text().strip()
        
        if not name:
            QMessageBox.warning(self, "Invalid Name", "Game name cannot be empty!")
            return
        
        if not version:
            QMessageBox.warning(self, "Invalid Version", "Version cannot be empty!")
            return
        
        # Collect selected categories
        main_selected = []
        sub_selected = []
        
        # Get main categories
        for i in range(self.main_categories_list.count()):
            item = self.main_categories_list.item(i)
            if item.checkState() == Qt.Checked:
                main_selected.append(item.text())
        
        # Get sub categories
        for i in range(self.sub_categories_list.count()):
            item = self.sub_categories_list.item(i)
            if item.checkState() == Qt.Checked:
                sub_selected.append(item.text())
        
        # Apply changes to game object
        self.game.name = name
        self.game.version = version
        self.game.type = self.type_combo.currentText()
        self.game.players = self.players_combo.currentText()
        
        # Handle categories - fill with nulls if needed
        # Main categories: pad to 5 with nulls
        while len(main_selected) < 5:
            main_selected.append("null")
        # Take only first 5
        main_selected = main_selected[:5]
        
        # Sub categories: pad to 3 with nulls
        while len(sub_selected) < 3:
            sub_selected.append("null")
        # Take only first 3
        sub_selected = sub_selected[:3]
        
        self.game.main_categories = main_selected
        self.game.sub_categories = sub_selected
        
        # Save manifest
        self.game.save_manifest()
        
        # Show success message
        QMessageBox.information(self, "Success", "Manifest updated successfully!")
        
        # Close dialog
        self.accept()


class AIManifestEditorDialog(QDialog):
    """AI-powered manifest editor for analyzing and updating existing game manifests"""
    
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.setWindowTitle(f"🤖 AI Manifest Editor - {game.name}")
        self.setFixedSize(800, 800)
        self.setModal(True)
        self.ai_processing = False
        self.generated_data = None
        self._setup_ui()
        self._load_current_game_data()
    
    def _setup_ui(self):
        """Setup the AI manifest editor UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Set dialog background
        self.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
            QLabel {
                color: white;
            }
            QTextEdit {
                background-color: #2a2a2a;
                color: white;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 8px;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                color: white;
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                padding: 8px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1a1a, stop:0.3 #1a1a1a, stop:0.7 #2a2a2a, stop:1 #1a1a1a);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #3a3a3a, stop:1 #2a2a2a);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #999;
                border-color: #555;
            }
        """)
        
        # Title
        title_label = QLabel(f"🤖 AI Manifest Editor")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: white; font-size: 20px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # Current game info
        info_label = QLabel(f"Current Game: {self.game.name}")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setStyleSheet("color: #E5E5E5; font-size: 14px; margin-bottom: 20px;")
        layout.addWidget(info_label)
        
        # Analyze button
        self.analyze_button = QPushButton("🤖 Analyze Game")
        self.analyze_button.setFixedSize(200, 40)
        self.analyze_button.setCursor(Qt.PointingHandCursor)
        self.analyze_button.clicked.connect(self._analyze_with_ai)
        layout.addWidget(self.analyze_button, alignment=Qt.AlignCenter)
        
        # Status label
        self.status_label = QLabel("Click 'Analyze Game' to generate AI-powered manifest data")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #E5E5E5; font-size: 12px; padding: 10px; margin-bottom: 10px;")
        layout.addWidget(self.status_label)
        
        # Generated content display
        content_group = QGroupBox("📋 AI Generated Content")
        content_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: white;
            }
        """)
        content_layout = QVBoxLayout(content_group)
        
        self.generated_content = QTextEdit()
        self.generated_content.setReadOnly(True)
        self.generated_content.setPlaceholderText("AI-generated manifest data will appear here...")
        self.generated_content.setMaximumHeight(300)
        content_layout.addWidget(self.generated_content)
        
        layout.addWidget(content_group)
        
        # Action buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(15)
        
        self.apply_button = QPushButton("✅ Apply Changes")
        self.apply_button.setFixedSize(150, 40)
        self.apply_button.setEnabled(False)
        self.apply_button.setCursor(Qt.PointingHandCursor)
        self.apply_button.clicked.connect(self._apply_ai_changes)
        
        self.cancel_button = QPushButton("❌ Cancel")
        self.cancel_button.setFixedSize(100, 40)
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.apply_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
    
    def _load_current_game_data(self):
        """Load current game data for display"""
        try:
            # Get current index.html content
            if self.game.html_path and self.game.html_path.exists():
                with open(self.game.html_path, 'r', encoding='utf-8') as f:
                    self.html_content = f.read()
            else:
                self.html_content = ""
                print(f"Warning: Game file not found at {self.game.html_path}")
        except Exception as e:
            self.html_content = ""
            print(f"Warning: Could not load current game file: {e}")
    
    def _analyze_with_ai(self):
        """Analyze current game with AI to generate manifest updates"""
        if not self.html_content:
            QMessageBox.warning(self, "Error", "Could not load game file content. Please check if the game file exists.")
            return
        
        self.ai_processing = True
        self.analyze_button.setEnabled(False)
        self.analyze_button.setText("🤖 Analyzing...")
        self.status_label.setText("AI is analyzing your current game...")
        self.status_label.setStyleSheet("color: #E5E5E5; font-size: 12px; padding: 10px; font-weight: bold;")
        
        # Use QTimer to run AI analysis in background thread
        QTimer.singleShot(100, self._run_ai_analysis)
    
    def _run_ai_analysis(self):
        """Run AI analysis in background"""
        try:
            # Create AI prompt for manifest analysis
            ai_prompt = self._create_ai_prompt(self.html_content)
            
            # Get AI model
            model, model_name = create_gamai_model()
            if not model:
                raise Exception("AI model not available. Please check your API key configuration.")
            
            # Generate response
            response = model.generate_content(ai_prompt)
            ai_response = response.text
            
            # Parse AI response
            manifest_data = self._parse_ai_response(ai_response)
            
            if manifest_data:
                # Store generated data
                self.generated_data = manifest_data
                # Display generated content
                self._display_generated_content(manifest_data)
                self.status_label.setText("✅ AI analysis completed successfully!")
                self.status_label.setStyleSheet("color: #E5E5E5; font-size: 12px; padding: 10px; font-weight: bold;")
                self.apply_button.setEnabled(True)
            else:
                raise Exception("Failed to parse AI response")
                
        except Exception as e:
            self.status_label.setText(f"❌ AI analysis failed: {str(e)}")
            self.status_label.setStyleSheet("color: #E5E5E5; font-size: 12px; padding: 10px;")
            QMessageBox.warning(self, "AI Analysis Failed", f"AI could not analyze the game: {str(e)}")
        
        finally:
            # Reset UI state
            self.ai_processing = False
            self.analyze_button.setEnabled(True)
            self.analyze_button.setText("🤖 Analyze Game")
    
    def _create_ai_prompt(self, html_content):
        """Create AI prompt for manifest analysis and updates"""
        # Truncate HTML if too long (keep reasonable length for AI processing)
        if len(html_content) > 8000:
            html_content = html_content[:4000] + "\n... [content truncated] ...\n" + html_content[-4000:]
        
        prompt = f"""ANALYZE THE FOLLOWING HTML GAME FILE AND SUGGEST IMPROVED MANIFEST.JSON CONTENT:

Current Game: {self.game.name}
Current Version: {self.game.version}
Current Type: {self.game.type}
Current Players: {self.game.players}

index.html content:
{html_content}

INSTRUCTIONS:
1. Analyze this HTML game content and suggest improved manifest values
2. Update the game name if you find a better fitting name
3. Suggest appropriate version (increment if this is an update)
4. Identify the game type (2D, 3D, etc.)
5. Determine optimal player count
6. Select up to 5 main categories from the available options
7. Suggest 3 sub-categories if applicable
8. Keep existing structure and only improve where beneficial

AVAILABLE MAIN CATEGORIES (choose up to 5):
- action: Action games (shooters, fighters, platformers)
- adventure: Adventure games (story-driven, exploration)
- arcade: Classic arcade games (retro style, simple controls)
- puzzle: Puzzle games (brain teasers, match-3, logic)
- strategy: Strategy games (tower defense, RTS, turn-based)
- sports: Sports games (football, basketball, racing)
- simulation: Simulation games (flight, city building, life)
- racing: Racing games (cars, motorcycles, vehicles)
- fighting: Fighting games (combat, martial arts)
- shooting: Shooting games (first-person, third-person)
- platformer: Platform games (jump and run, side-scrolling)
- rpg: Role-playing games (character progression, story)
- survival: Survival games (resource management, crafting)
- horror: Horror games (scary, survival horror)
- educational: Educational games (learning, training)
- casual: Casual games (simple, quick play)
- music: Music games (rhythm, instruments)
- card: Card games (poker, solitaire, trading cards)
- casino: Casino games (slots, gambling)
- board: Board games (chess, checkers, strategy board)
- trivia: Quiz games (questions, answers, knowledge)
- word: Word games (spelling, vocabulary, crosswords)

AVAILABLE SUB-CATEGORIES:
- multiplayer: Multiplayer games (online, local co-op)
- singleplayer: Single player games
- online: Online play supported
- offline: Offline only
- touch: Touch controls (mobile/tablet)
- keyboard: Keyboard controls
- mouse: Mouse controls
- controller: Game controller support
- web: Web browser compatible
- mobile: Mobile optimized
- desktop: Desktop optimized
- 3d: Three-dimensional graphics
- 2d: Two-dimensional graphics
- retro: Retro/classic style
- modern: Modern graphics and features
- indie: Independent/small developer
- free: Free to play
- demo: Demo or trial version

RETURN ONLY THE JSON FORMAT BELOW:
{{
  "name": "Game Name (improved if needed)",
  "version": "1.0.1 (increment if update)",
  "type": "2D or 3D",
  "players": "1, 2, 3, 4, etc.",
  "main_categories": ["category1", "category2", "category3"],
  "sub_categories": ["subcategory1", "subcategory2", "subcategory3"]
}}

Respond ONLY with the JSON content, no additional text.
"""
        return prompt
    
    def _parse_ai_response(self, ai_response):
        """Parse AI response to extract manifest data"""
        try:
            # Extract JSON from AI response
            # Look for JSON content between { and }
            start_idx = ai_response.find('{')
            end_idx = ai_response.rfind('}')
            
            if start_idx == -1 or end_idx == -1 or start_idx >= end_idx:
                raise Exception("No valid JSON found in AI response")
            
            json_str = ai_response[start_idx:end_idx + 1]
            
            # Parse JSON
            manifest_data = json.loads(json_str)
            
            # Validate required fields
            required_fields = ['name', 'version', 'type', 'players', 'main_categories', 'sub_categories']
            for field in required_fields:
                if field not in manifest_data:
                    raise Exception(f"Missing required field: {field}")
            
            # Ensure categories are lists
            if not isinstance(manifest_data['main_categories'], list):
                manifest_data['main_categories'] = [manifest_data['main_categories']]
            if not isinstance(manifest_data['sub_categories'], list):
                manifest_data['sub_categories'] = [manifest_data['sub_categories']]
            
            # Limit main categories to 5
            if len(manifest_data['main_categories']) > 5:
                manifest_data['main_categories'] = manifest_data['main_categories'][:5]
            
            # Limit sub categories to 3
            if len(manifest_data['sub_categories']) > 3:
                manifest_data['sub_categories'] = manifest_data['sub_categories'][:3]
            
            return manifest_data
            
        except json.JSONDecodeError as e:
            raise Exception(f"Invalid JSON in AI response: {e}")
        except Exception as e:
            raise Exception(f"Error parsing AI response: {e}")
    
    def _display_generated_content(self, manifest_data):
        """Display the AI generated manifest content"""
        display_text = f"""🤖 AI GENERATED MANIFEST DATA:

📝 Name: {manifest_data['name']}
🔢 Version: {manifest_data['version']}
🎮 Type: {manifest_data['type']}
👥 Players: {manifest_data['players']}
📊 Main Categories: {', '.join(manifest_data['main_categories'])}
📋 Sub Categories: {', '.join(manifest_data['sub_categories'])}

📄 JSON FORMAT:
{json.dumps(manifest_data, indent=2)}"""
        
        self.generated_content.setText(display_text)
    
    def _apply_ai_changes(self):
        """Apply AI generated changes to the manifest"""
        if not self.generated_data:
            QMessageBox.warning(self, "Error", "No AI data to apply.")
            return
        
        try:
            # Apply changes to game object (similar to manual editor)
            self.game.name = self.generated_data['name']
            self.game.version = self.generated_data['version']
            self.game.type = self.generated_data['type']
            self.game.players = self.generated_data['players']
            
            # Handle categories - pad with nulls if needed
            main_selected = self.generated_data['main_categories'][:]
            sub_selected = self.generated_data['sub_categories'][:]
            
            # Main categories: pad to 5 with nulls
            while len(main_selected) < 5:
                main_selected.append("null")
            # Take only first 5
            main_selected = main_selected[:5]
            
            # Sub categories: pad to 3 with nulls
            while len(sub_selected) < 3:
                sub_selected.append("null")
            # Take only first 3
            sub_selected = sub_selected[:3]
            
            self.game.main_categories = main_selected
            self.game.sub_categories = sub_selected
            
            # Save manifest
            self.game.save_manifest()
            
            # Show success message
            QMessageBox.information(self, "Success", f"Manifest updated successfully with AI suggestions!\n\nChanges applied:\n• Name: {self.generated_data['name']}\n• Version: {self.generated_data['version']}\n• Type: {self.generated_data['type']}\n• Players: {self.generated_data['players']}")
            
            # Close dialog
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply AI changes: {str(e)}")


class ExportGameDialog(QDialog):
    """Dialog for exporting selected games to zip files"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Games")
        self.setFixedSize(600, 500)
        self.setModal(True)
        self.selected_games = []
        self._setup_ui()
        self._load_games()
    
    def _setup_ui(self):
        """Setup the export games dialog UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Title
        title_label = QLabel("Select Games to Export")
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: white; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # Instructions
        instructions_label = QLabel("Choose one or more games to export as zip files.\nSingle export: game_name_v1.1.1.zip\nMulti-export: timestamp_XX.zip")
        instructions_label.setStyleSheet("font-size: 12px; color: #ccc; margin-bottom: 15px;")
        instructions_label.setWordWrap(True)
        layout.addWidget(instructions_label)
        
        # Games list with scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFixedHeight(300)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 2px solid #3a3a3a;
                border-radius: 5px;
                background-color: #2a2a2a;
            }
            QScrollBar:vertical {
                background-color: #2a2a2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
        """)
        
        # Games container
        self.games_container = QWidget()
        self.games_layout = QVBoxLayout(self.games_container)
        self.games_layout.setSpacing(5)
        self.games_layout.setContentsMargins(10, 10, 10, 10)
        
        scroll_area.setWidget(self.games_container)
        layout.addWidget(scroll_area)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        # Select All button
        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 16px;
            }
            QPushButton:hover {
                border: 2px solid #E5E5E5;
            }
        """)
        self.select_all_button.clicked.connect(self._select_all_games)
        button_layout.addWidget(self.select_all_button)
        
        button_layout.addStretch()
        
        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 20px;
            }
            QPushButton:hover {
                border: 2px solid #E5E5E5;
            }
        """)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)
        
        # Export button
        self.export_button = QPushButton("Export Selected")
        self.export_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
                padding: 8px 20px;
            }
            QPushButton:hover {
                border: 2px solid #E5E5E5;
            }
        """)
        self.export_button.clicked.connect(self._export_selected)
        button_layout.addWidget(self.export_button)
        
        layout.addLayout(button_layout)
    
    def _load_games(self):
        """Load available games into the list"""
        try:
            # Get main window to access games
            main_window = self.parent()
            if not main_window or not hasattr(main_window, 'games'):
                self._show_error("Unable to load games list.")
                return
            
            games = main_window.games
            if not games:
                no_games_label = QLabel("No games available to export.")
                no_games_label.setStyleSheet("color: #999; font-style: italic; padding: 20px;")
                self.games_layout.addWidget(no_games_label)
                return
            
            # Create game items
            for game in games:
                game_widget = self._create_game_item(game)
                self.games_layout.addWidget(game_widget)
            
            self.games_layout.addStretch()
            
        except Exception as e:
            self._show_error(f"Failed to load games: {str(e)}")
    
    def _create_game_item(self, game):
        """Create a widget for a single game item"""
        widget = QWidget()
        widget.setStyleSheet("""
            QWidget {
                background-color: #3a3a3a;
                border: 1px solid #555;
                border-radius: 5px;
                padding: 10px;
                margin: 2px;
            }
            QWidget:hover {
                background-color: #4a4a4a;
                border: 1px solid #666;
            }
        """)
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 8, 10, 8)
        
        # Checkbox
        checkbox = QCheckBox()
        checkbox.setStyleSheet("""
            QCheckBox {
                color: white;
                font-size: 14px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #666;
                border-radius: 3px;
                background-color: #2a2a2a;
            }
            QCheckBox::indicator:checked {
                background-color: #E5E5E5;
                border-color: #E5E5E5;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #E5E5E5;
            }
        """)
        
        # Game info
        info_layout = QVBoxLayout()
        
        # Game name
        name_label = QLabel(game.name)
        name_label.setStyleSheet("font-size: 14px; font-weight: bold; color: white;")
        
        # Game details
        details_text = f"v{game.version} | {game.type} | {game.players}"
        details_label = QLabel(details_text)
        details_label.setStyleSheet("font-size: 11px; color: #ccc;")
        
        info_layout.addWidget(name_label)
        info_layout.addWidget(details_label)
        info_layout.addStretch()
        
        layout.addWidget(checkbox)
        layout.addLayout(info_layout)
        layout.addStretch()
        
        # Store references for later access
        widget.checkbox = checkbox
        widget.game = game
        
        return widget
    
    def _select_all_games(self):
        """Select or deselect all games"""
        all_checked = all(item.checkbox.isChecked() for item in self._get_game_items())
        
        for item in self._get_game_items():
            item.checkbox.setChecked(not all_checked)
    
    def _get_game_items(self):
        """Get all game item widgets"""
        items = []
        for i in range(self.games_layout.count()):
            item = self.games_layout.itemAt(i)
            if item.widget() and hasattr(item.widget(), 'checkbox'):
                items.append(item.widget())
        return items
    
    def _export_selected(self):
        """Export the selected games"""
        selected_items = [item for item in self._get_game_items() if item.checkbox.isChecked()]
        
        if not selected_items:
            QMessageBox.information(self, "No Selection", "Please select at least one game to export.")
            return
        
        self.selected_games = [item.game for item in selected_items]
        self.accept()
    
    def get_selected_games(self):
        """Get the list of selected games"""
        return self.selected_games
    
    def _show_error(self, message):
        """Show error message"""
        error_label = QLabel(message)
        error_label.setStyleSheet("color: #E5E5E5; font-style: italic; padding: 20px;")
        self.games_layout.addWidget(error_label)


class CodeEditorWidget(QWidget):
    """Code editor widget for HTML5 game development - embedded in main window"""
    
    gameSaved = pyqtSignal(object)
    finishRequested = pyqtSignal()
    
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self.unsaved_changes = False
        self.auto_refresh_timer = None  # Timer for automatic preview updates
        self.is_running = False  # Flag to track if game is currently running
        self._setup_ui()
        self._load_game_code()
        self._setup_shortcuts()
        self._setup_auto_refresh()
    
    def _setup_ui(self):
        """Setup editor UI"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Top toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet("background-color: #2a2a2a; border-bottom: 1px solid #3a3a3a;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 0, 10, 0)
        
        # Run button
        self.run_button = QPushButton("▶ Run Game")
        self.run_button.setFixedSize(120, 35)
        self.run_button.setCursor(Qt.PointingHandCursor)
        self.run_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
        """)
        self.run_button.clicked.connect(self._run_game)
        
        # Stop button
        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setFixedSize(100, 35)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }

            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.stop_button.clicked.connect(self._stop_game)
        
        # Save button
        self.save_button = QPushButton("💾 Save")
        self.save_button.setFixedSize(100, 35)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.save_button.clicked.connect(self._save_game)
        
        # Finish button
        self.finish_button = QPushButton("✕ Finish")
        self.finish_button.setFixedSize(100, 35)
        self.finish_button.setCursor(Qt.PointingHandCursor)
        self.finish_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.finish_button.clicked.connect(self._finish_editing)
        
        toolbar_layout.addWidget(self.run_button)
        toolbar_layout.addWidget(self.stop_button)
        toolbar_layout.addWidget(self.save_button)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.finish_button)
        
        main_layout.addWidget(toolbar)
        
        # Splitter for code editor and preview
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        
        # Code editor (left panel)
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(10, 10, 5, 10)
        
        # Editor label
        editor_label = QLabel("HTML + CSS + JavaScript")
        editor_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        editor_layout.addWidget(editor_label)
        
        # Code editor
        self.code_editor = QPlainTextEdit()
        self.code_editor.setMinimumSize(600, 400)  # Set minimum size for readability
        self.code_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.code_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #E5E5E5;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                font-family: 'Courier New', monospace;
                font-size: 14px;
                padding: 15px;
            }
            QPlainTextEdit:focus {
                border-color: #E5E5E5;
            }
        """)
        self.code_editor.textChanged.connect(self._on_text_changed)
        editor_layout.addWidget(self.code_editor)
        
        # Preview panel (right panel)
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(5, 10, 10, 10)
        
        # Preview label
        self.preview_label = QLabel("Live Preview")
        self.preview_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        preview_layout.addWidget(self.preview_label)
        
        # Preview web view
        self.preview_webview = QWebEngineView()
        self.preview_webview.setStyleSheet("""
            QWebEngineView {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
            }
        """)
        preview_layout.addWidget(self.preview_webview)
        
        # Add panels to splitter
        splitter.addWidget(editor_widget)
        splitter.addWidget(preview_widget)
        splitter.setSizes([600, 600])  # Equal initial sizes
        
        main_layout.addWidget(splitter)
        main_layout.addWidget(splitter)
        
        # Initialize preview with current content
        self._update_preview()
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        # Additional shortcuts
        QShortcut(QKeySequence(Qt.Key_F5), self, activated=self._run_game)
        QShortcut(QKeySequence(Qt.Key_F9), self, activated=self._update_preview)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._finish_editing)
    
    def _setup_auto_refresh(self):
        """Setup automatic preview refresh - ultra fast for live updates"""
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self._update_preview)
        self.auto_refresh_timer.start(100)  # Update every 100ms for smooth live experience
        self.last_preview_content = ""  # Track last previewed content to avoid unnecessary updates
    
    def _load_game_code(self):
        """Load existing game code"""
        try:
            if self.game.html_path.exists():
                with open(self.game.html_path, 'r', encoding='utf-8') as f:
                    self.code_editor.setPlainText(f.read())
            else:
                # Load default template
                self._load_default_template()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load game code: {e}")
            self._load_default_template()
    
    def _load_default_template(self):
        """Load default HTML5 template"""
        template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Game</title>
    <style>
        body {
            margin: 0;
            padding: 20px;
            font-family: Arial, sans-serif;
            background-color: #2a2a2a;
            color: white;
        }
        canvas {
            border: 2px solid #E5E5E5;
            display: block;
            margin: 0 auto;
            background-color: #1a1a1a;
        }
        .info {
            text-align: center;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <div class="info">
        <h1>My HTML5 Game</h1>
        <p>Start coding your game here!</p>
    </div>
    <canvas id="gameCanvas" width="800" height="600"></canvas>
    
    <script>
        // Game code goes here
        const canvas = document.getElementById('gameCanvas');
        const ctx = canvas.getContext('2d');
        
        // Basic game loop
        function gameLoop() {
            // Clear canvas
            ctx.fillStyle = '#1a1a1a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            
            // Draw game content
            ctx.fillStyle = '#E5E5E5';
            ctx.font = '30px Arial';
            ctx.textAlign = 'center';
            ctx.fillText('Hello, Game Developer!', canvas.width / 2, canvas.height / 2);
            
            requestAnimationFrame(gameLoop);
        }
        
        // Start the game
        gameLoop();
    </script>
</body>
</html>"""
        self.code_editor.setPlainText(template)
    
    def _on_text_changed(self):
        """Handle text changes"""
        self.unsaved_changes = True
        self._update_window_title()
        # Update preview with new content
        self._update_preview()
    
    def _update_window_title(self):
        """Update window title to show unsaved changes"""
        title = f"GameBox Editor - {self.game.name}"
        if self.unsaved_changes:
            title += " *"
        self.setWindowTitle(title)
    
    def _save_game(self):
        """Save game code to file with edit count tracking"""
        try:
            with open(self.game.html_path, 'w', encoding='utf-8') as f:
                f.write(self.code_editor.toPlainText())
            
            # Increment edit count and save to manifest
            self.game.edits += 1
            self.game.save_manifest()
            
            self.unsaved_changes = False
            self._update_window_title()
            self.gameSaved.emit(self.game)
            
            QMessageBox.information(self, "Success", f"Game saved successfully!\nEdit count: {self.game.edits}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save game: {e}")
    
    def _update_preview(self):
        """Update live preview - ultra fast, smooth, no window refresh"""
        try:
            # Don't update preview if game is currently running
            if self.is_running:
                return
                
            html_content = self.code_editor.toPlainText()
            
            # Only update if content actually changed (optimization)
            if hasattr(self, 'last_preview_content') and html_content == self.last_preview_content:
                return
            
            # Store current content for next comparison
            self.last_preview_content = html_content
            
            if html_content.strip():
                # Use setHtml() directly for instant updates without full window refresh
                # This is much faster and doesn't cause UI flickering
                self.preview_webview.setHtml(html_content)
                
            else:
                # Show empty state using setHtml() for consistency
                self.preview_webview.setHtml("""
                    <html>
                    <head>
                        <meta charset="UTF-8">
                        <style>
                            body {
                                background-color: #2a2a2a;
                                color: white;
                                font-family: 'Segoe UI', Arial, sans-serif;
                                text-align: center;
                                padding: 50px;
                                margin: 0;
                            }
                            h2 {
                                color: #999;
                                margin-bottom: 10px;
                                font-weight: 300;
                            }
                            p {
                                color: #666;
                                font-size: 13px;
                            }
                        </style>
                    </head>
                    <body>
                        <h2>🎮 Live Preview</h2>
                        <p>Start coding your HTML5 game to see it here.<br>
                        Your changes appear instantly!</p>
                    </body>
                    </html>
                """)
            
        except Exception as e:
            # Show error in preview using setHtml() for consistency
            self.preview_webview.setHtml(f"""
                <html>
                <head>
                    <meta charset="UTF-8">
                    <style>
                        body {{
                            background-color: #2a2a2a;
                            color: white;
                            font-family: 'Segoe UI', Arial, sans-serif;
                            text-align: center;
                            padding: 50px;
                            margin: 0;
                        }}
                        h2 {{
                            color: #E5E5E5;
                            margin-bottom: 10px;
                            font-weight: 300;
                        }}
                        p {{
                            color: #999;
                            font-size: 13px;
                        }}
                    </style>
                </head>
                <body>
                    <h2>⚠️ Preview Error</h2>
                    <p>Unable to display preview: {str(e)}</p>
                    <p>Please check your HTML code for syntax errors.</p>
                </body>
                </html>
            """)
    
    def _run_game(self):
        """Run game in preview area - load from current editor content for better state preservation"""
        try:
            # Mark game as running to pause auto-refresh
            self.is_running = True
            
            # Get current editor content instead of always saving to file
            html_content = self.code_editor.toPlainText()
            
            if html_content.strip():
                # Load from current content to preserve game state
                self.preview_webview.setHtml(html_content)
                
                # Update UI state to show running mode
                self.run_button.setEnabled(False)
                self.stop_button.setEnabled(True)
                self.preview_label.setText("Game Running (Stop to return to preview)")
                self.preview_label.setStyleSheet("color: #E5E5E5; font-size: 14px; font-weight: bold; margin-bottom: 5px;")
            else:
                QMessageBox.information(self, "No Game Code", "Please write some HTML5 game code first.")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to run game: {e}")
    
    def _stop_game(self):
        """Stop game and return to live preview mode"""
        # Mark game as not running to resume auto-refresh
        self.is_running = False
        
        # Clear current webview content and return to live preview
        self._update_preview()
        
        # Update UI state to show preview mode
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.preview_label.setText("Live Preview")
        self.preview_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 5px;")

    def _finish_editing(self):
        """Finish editing and return to main menu"""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self, 
                "Unsaved Changes",
                "You have unsaved changes. Do you want to save before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save
            )
            
            if reply == QMessageBox.Save:
                self._save_game()
            elif reply == QMessageBox.Cancel:
                return
        
        # Ensure game is not running
        self.is_running = False
        
        # Stop auto-refresh timer and clean up attributes
        if self.auto_refresh_timer:
            self.auto_refresh_timer.stop()
            self.auto_refresh_timer = None
        
        # Clean up preview tracking
        if hasattr(self, 'last_preview_content'):
            delattr(self, 'last_preview_content')
        
        self.finishRequested.emit()
        self.close()
    
# --- 3. UI Components ---

class GameButton(QPushButton):
    """Custom button for displaying a game box"""
    
    gameClicked = pyqtSignal(object)
    
    def __init__(self, game, parent=None):
        super().__init__(parent)
        self.game = game
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup button UI"""
        # Fixed size for the game box with better dimensions
        self.setMinimumSize(QSize(280, 350))  # Increased from 250x300
        self.setCursor(Qt.PointingHandCursor)
        
        # Internal widget to hold content for better layout control
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Icon/Placeholder
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setFixedSize(220, 220)  # Increased from 200x200
        self._set_icon(icon_label)
        layout.addWidget(icon_label)
        
        # Game name
        name_label = QLabel(self.game.name)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        layout.addWidget(name_label)
        
        # Version
        version_label = QLabel(f"v{self.game.version}")
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(version_label)
        
        # Game metadata with categories and auto-tracking
        main_cat_display = format_categories_for_display(self.game.main_categories, "Main-Category", MAIN_CATEGORIES)
        sub_cat_display = format_categories_for_display(self.game.sub_categories, "Sub-Category", SUB_CATEGORIES)
        
        # Compact auto-tracking display for game list - show total minutes only
        total_minutes = (self.game.time_played.get('minutes', 0) + 
                        self.game.time_played.get('hours', 0) * 60 + 
                        self.game.time_played.get('days', 0) * 24 * 60 + 
                        self.game.time_played.get('weeks', 0) * 7 * 24 * 60 + 
                        self.game.time_played.get('months', 0) * 30 * 24 * 60)
        # NEW: Add rating to compact display
        rating_info = f"Rating: {self.game.get_rating_text()}"
        auto_tracking = f"Time: {total_minutes}m | Edits: {self.game.edits} | Played: {self.game.played_times} times"  # NEW: Add played_times
        
        metadata_label = QLabel(f"Type: {self.game.type} | Players: {self.game.players}\n{rating_info}\n{auto_tracking}")
        metadata_label.setAlignment(Qt.AlignCenter)
        metadata_label.setStyleSheet("color: #E5E5E5; font-size: 11px; font-weight: bold;")
        layout.addWidget(metadata_label)
        
        # Set the content widget as the button's layout
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(content_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Styling
        self.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #3a3a3a;
                border-radius: 10px;
                padding: 0; /* Remove default padding */
            }
            QPushButton:hover {
                background-color: #3a3a3a;
                border: 2px solid #4a4a4a;
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
            }
        """)
        
        # Connect click
        self.clicked.connect(lambda: self.gameClicked.emit(self.game))
    
    def _set_icon(self, label):
        """Set game icon or fallback to text"""
        if self.game.icon_path:
            pixmap = QPixmap(str(self.game.icon_path))
            if not pixmap.isNull():
                # Scale icon to fit the 200x200 area
                label.setPixmap(pixmap.scaled(200, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        
        # Fallback: text icon (first 2 letters of the game name)
        initials = "".join(word[0] for word in self.game.name.split() if word).upper()[:2]
        if not initials:
            initials = "?"
            
        # Create a placeholder pixmap with black background and white text
        pixmap = QPixmap(200, 200)
        pixmap.fill(QColor(0, 0, 0)) # Black background
        
        painter = QPainter(pixmap)
        painter.setPen(QColor(255, 255, 255)) # White text
        font = QFont("Arial", 48, QFont.Bold)
        painter.setFont(font)
        
        # Draw text centered
        rect = pixmap.rect()
        painter.drawText(rect, Qt.AlignCenter, initials)
        painter.end()
        
        label.setPixmap(pixmap)
        label.setStyleSheet("border-radius: 10px;") # Keep the rounded look
        label.setAlignment(Qt.AlignCenter)


class GameList(QWidget):
    """Widget for displaying games in a vertical list with scroll buttons"""
    
    gameSelected = pyqtSignal(object)
    
    def __init__(self, parent=None):
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #0a0a0a; }")
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff) # Hide default scrollbar
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_step = 280  # Optimized scroll step for smoother incremental movement
        self.scroll_animation = None  # Animation instance
        
        # View mode management
        self.is_grid_view = False  # Default is vertical layout
        self.current_games = []    # Store current games for layout switching
        
        # Main menu AI state
        self.gamai_chat_active = False
        self.gamai_chat_widget = None

        super().__init__(parent)
        self._setup_ui()
        self._setup_shortcuts()
        self._setup_mouse_wheel()
    
    def _setup_ui(self):
        """Setup list UI"""
        
        # Main content widget for the scroll area
        self.list_widget = QWidget()
        self.list_widget.setStyleSheet("background-color: #0a0a0a;")
        self.list_layout = QVBoxLayout(self.list_widget)
        self.list_layout.setSpacing(30)
        self.list_layout.setContentsMargins(50, 50, 50, 50)
        self.list_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter) # Align items to the top center

        self.scroll_area.setWidget(self.list_widget)

        # Scroll control buttons
        self.up_button = QPushButton("▲")
        self.down_button = QPushButton("▼")
        self.up_button.setFixedSize(50, 50)
        self.down_button.setFixedSize(50, 50)
        self.up_button.setCursor(Qt.PointingHandCursor)
        self.down_button.setCursor(Qt.PointingHandCursor)
        self.up_button.clicked.connect(self._scroll_up)
        self.down_button.clicked.connect(self._scroll_down)
        
        # Enhanced styling for scroll buttons with smooth animations
        button_style = """
            QPushButton {
                background-color: #2d2d2d;
                color: white;
                border: 2px solid #444;
                border-radius: 12px;
                font-size: 24px;
                font-weight: bold;
                min-width: 55px;
                min-height: 55px;
                max-width: 55px;
                max-height: 55px;
            }
            QPushButton:hover {
                background-color: #3d3d3d;
                border-color: #E5E5E5;
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #1a1a1a;
                border-color: #E5E5E5;
                transform: translateY(1px);
            }
        """
        self.up_button.setStyleSheet(button_style)
        self.down_button.setStyleSheet(button_style)

        # Layout for buttons
        button_layout = QVBoxLayout()
        button_layout.addWidget(self.up_button)
        button_layout.addStretch(1) # Push buttons to the top and bottom of the available space
        button_layout.addWidget(self.down_button)
        button_layout.setContentsMargins(10, 50, 10, 50) # Match vertical margins of the list

        # Main layout: List on the left, buttons on the right
        main_h_layout = QHBoxLayout(self)
        main_h_layout.setContentsMargins(0, 0, 0, 0)
        main_h_layout.addWidget(self.scroll_area, 1) # List takes most space
        main_h_layout.addLayout(button_layout) # Buttons on the right

    def _scroll_up(self):
        """Smooth scroll up animation"""
        self._animate_scroll(-self.scroll_step)

    def _scroll_down(self):
        """Smooth scroll down animation"""
        self._animate_scroll(self.scroll_step)
    
    def _scroll_up_fixed(self, steps=1):
        """Scroll up by fixed number of steps for page up functionality"""
        self._animate_scroll(-self.scroll_step * steps)
    
    def _scroll_down_fixed(self, steps=1):
        """Scroll down by fixed number of steps for page down functionality"""
        self._animate_scroll(self.scroll_step * steps)
    
    def _animate_scroll(self, delta):
        """Smooth scroll animation with adaptive duration"""
        vbar = self.scroll_area.verticalScrollBar()
        current_value = vbar.value()
        target_value = max(0, min(vbar.maximum(), current_value + delta))
        
        if current_value == target_value:
            return  # Already at target position, no animation needed
        
        # Calculate distance for adaptive duration
        distance = abs(target_value - current_value)
        
        # Stop any existing animation to prevent conflicts
        if self.scroll_animation:
            self.scroll_animation.stop()
        
        # Create smooth animation with adaptive duration
        self.scroll_animation = QPropertyAnimation(vbar, b"value")
        
        # Adaptive duration: longer for longer distances, minimum 150ms, maximum 400ms
        duration = max(150, min(400, int(distance * 0.6) + 100))
        self.scroll_animation.setDuration(duration)
        
        self.scroll_animation.setStartValue(current_value)
        self.scroll_animation.setEndValue(target_value)
        
        # Use smooth easing curve for natural feel
        self.scroll_animation.setEasingCurve(QEasingCurve.OutQuart)
        
        # Add subtle overshoot effect for premium feel
        self.scroll_animation.finished.connect(self._on_scroll_animation_finished)
        
        self.scroll_animation.start()
        
        # Optional: Add visual feedback
        self._create_scroll_feedback(delta > 0)
    
    def _on_scroll_animation_finished(self):
        """Handle animation completion for any cleanup"""
        # Could add subtle bounce effect here if desired
        pass
    
    def _create_scroll_feedback(self, is_scrolling_down):
        """Create subtle visual feedback for scroll operation"""
        # Subtle button press effect
        target_button = self.down_button if is_scrolling_down else self.up_button
        
        # Create a brief visual pulse effect
        animation = QPropertyAnimation(target_button, b"geometry")
        animation.setDuration(100)
        animation.setStartValue(target_button.geometry())
        
        current_geom = target_button.geometry()
        if is_scrolling_down:
            # Briefly move down button down slightly
            pulse_rect = QRect(current_geom.x(), current_geom.y() + 2, 
                              current_geom.width(), current_geom.height())
        else:
            # Briefly move up button up slightly  
            pulse_rect = QRect(current_geom.x(), current_geom.y() - 2, 
                              current_geom.width(), current_geom.height())
        
        animation.setEndValue(pulse_rect)
        animation.setEasingCurve(QEasingCurve.OutQuad)
        
        # Create return animation
        return_animation = QPropertyAnimation(target_button, b"geometry")
        return_animation.setDuration(100)
        return_animation.setStartValue(pulse_rect)
        return_animation.setEndValue(current_geom)
        return_animation.setEasingCurve(QEasingCurve.OutQuad)
        return_animation.setStartValue(pulse_rect)
        return_animation.setEndValue(current_geom)
        
        # Chain animations
        animation.finished.connect(return_animation.start)
        animation.start()
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts for main menu"""
        QShortcut(QKeySequence(Qt.Key_F10), self, activated=self._toggle_gamai_chat)
        QShortcut(QKeySequence(Qt.Key_Up), self, activated=self._scroll_up)
        QShortcut(QKeySequence(Qt.Key_Down), self, activated=self._scroll_down)
        QShortcut(QKeySequence(Qt.Key_PageUp), self, activated=lambda: self._scroll_up_fixed(3))
        QShortcut(QKeySequence(Qt.Key_PageDown), self, activated=lambda: self._scroll_down_fixed(3))
    
    def _setup_mouse_wheel(self):
        """Setup mouse wheel scrolling support"""
        # Enable smooth mouse wheel scrolling
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # Keep scrollbar hidden
        self.scroll_area.viewport().setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.scroll_area.viewport().installEventFilter(self)
    
    def wheelEvent(self, event):
        """Handle mouse wheel events for smooth scrolling"""
        delta = event.angleDelta().y()
        
        if delta > 0:
            # Scroll up
            self._scroll_up()
        elif delta < 0:
            # Scroll down
            self._scroll_down()
        
        # Accept the event to prevent default scrolling
        event.accept()
    
    def eventFilter(self, obj, event):
        """Filter events for enhanced scroll experience"""
        if event.type() == QEvent.Wheel:
            # Enhance wheel scroll with more granular steps
            delta = event.angleDelta().y()
            if delta != 0:
                # Calculate fractional scroll for smoother feel
                scroll_delta = self.scroll_step // 2  # Half step for wheel
                if delta > 0:
                    self._animate_scroll(-scroll_delta)
                else:
                    self._animate_scroll(scroll_delta)
                event.accept()
                return True
        
        return super().eventFilter(obj, event)
    
    def _toggle_gamai_chat(self):
        """Toggle GAMAI chat panel using F10 in main menu"""
        if not self.gamai_chat_active:
            # Enter GAMAI chat mode
            self._enter_gamai_chat_mode()
        else:
            # Exit GAMAI chat mode  
            self._exit_gamai_chat_mode()
    
    def _enter_gamai_chat_mode(self):
        """Enter GAMAI chat mode in main menu"""
        try:
            # Create GAMAI chat widget if it doesn't exist
            if not self.gamai_chat_widget:
                self.gamai_chat_widget = GamaiChatWidget(context_type="global", parent=self)
                # Add to main layout
                main_h_layout = self.layout()
                # Insert GAMAI widget before scroll area
                main_h_layout.insertWidget(0, self.gamai_chat_widget)
            
            # Show GAMAI chat panel
            self.gamai_chat_widget.setVisible(True)
            
            # Set minimum size for GAMAI chat widget (no setSizes for QHBoxLayout)
            self.gamai_chat_widget.setMinimumWidth(300)
            
            # Update UI state
            self.gamai_chat_active = True
            
            # Update AI context - user opened GAMAI chat in main menu
            GAMAI_CONTEXT.update_context_status("global", "user opened GAMAI chat in main menu")
            
            # Update available games context
            if self.current_games:
                game_names = [game.name for game in self.current_games]
                GAMAI_CONTEXT.update_context_status("global", f"Available games: {', '.join(game_names)}")
            
            # Update AI capabilities context with explicit JSON format requirements
            GAMAI_CONTEXT.update_context_status("global", "AVAILABLE TOOLS: play_game_name (opens games in play mode), edit_game_name (opens games in editor mode)")
            GAMAI_CONTEXT.update_context_status("global", "JSON FORMAT REQUIRED: {\"tool\": \"play_game_name\", \"parameters\": {\"name\": \"GameName\"}} for play mode")
            GAMAI_CONTEXT.update_context_status("global", "JSON FORMAT REQUIRED: {\"tool\": \"edit_game_name\", \"parameters\": {\"name\": \"GameName\"}} for edit mode")
            
        except Exception as e:
            print(f"Error entering GAMAI chat mode: {e}")
    
    def _exit_gamai_chat_mode(self):
        """Exit GAMAI chat mode in main menu"""
        try:
            # Hide GAMAI chat panel
            if self.gamai_chat_widget:
                self.gamai_chat_widget.setVisible(False)
                # Also reset minimum width
                self.gamai_chat_widget.setMinimumWidth(0)
            
            # Update UI state
            self.gamai_chat_active = False
            
            # Force layout update
            self.layout().update()
            
            # Update AI context - user closed GAMAI chat
            GAMAI_CONTEXT.update_context_status("global", "user closed GAMAI chat in main menu")
            
        except Exception as e:
            print(f"Error exiting GAMAI chat mode: {e}")

    def display_games(self, games):
        """Display games in current view mode"""
        # Store current games for layout switching
        self.current_games = games
        
        # Clear existing list
        self._clear_list()
        
        if self.is_grid_view:
            self._create_grid_layout(games)
        else:
            self._create_vertical_layout(games)
        self.list_layout.addStretch(1)
        
        # Update AI context with available games if GAMAI is active
        if self.gamai_chat_active and games:
            game_names = [game.name for game in games]
            GAMAI_CONTEXT.update_context_status("global", f"Available games: {', '.join(game_names)}")
    
    def open_game_by_name(self, game_name, mode="play"):
        """Open a game by name (called from AI tool-calls)"""
        # Find the game by name (case-insensitive)
        found_game = None
        for game in self.current_games:
            if game.name.lower() == game_name.lower():
                found_game = game
                break
        
        if found_game:
            # Emit signal to open the game
            self.gameSelected.emit(found_game)
            
            # Update AI context
            GAMAI_CONTEXT.update_context_status("global", f"AI opened game '{found_game.name}' in {mode} mode")
            return True
        else:
            # Game not found
            GAMAI_CONTEXT.update_context_status("global", f"AI attempted to open game '{game_name}' but it was not found")
            return False
    
    def get_available_games(self):
        """Get list of available game names for AI"""
        return [game.name for game in self.current_games]
    
    def highlight_game(self, game_name):
        """Highlight a specific game by name"""
        # Find the button for the specified game
        for i in range(self.list_layout.count()):
            item = self.list_layout.itemAt(i)
            if item.widget() and isinstance(item.widget(), GameButton):
                button = item.widget()
                if button.game.name.lower() == game_name.lower():
                    # Highlight the button
                    button.setStyleSheet("""
                        QPushButton {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                            border: 2px solid #E5E5E5;
                            border-radius: 10px;
                            font-size: 18px;
                            font-weight: bold;
                            color: white;
                            margin: 10px;
                            padding: 20px;
                        }
                        QPushButton:hover {
                            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                                stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                            border: 2px solid #E5E5E5;
                        }
                        QPushButton:pressed {
                            background-color: #E5E5E5;
                        }
                    """)
                    # Scroll to make the highlighted game visible
                    QTimer.singleShot(100, lambda: self._scroll_to_button(button))
                    break
    
    def _scroll_to_button(self, button):
        """Scroll to make the specified button visible"""
        try:
            # Get the scroll area's geometry and the button's geometry
            scroll_area_rect = self.scroll_area.geometry()
            button_rect = button.geometry()
            
            # Calculate if the button is outside the visible area
            if button_rect.top() < 0 or button_rect.bottom() > scroll_area_rect.height():
                # Scroll to the button
                vbar = self.scroll_area.verticalScrollBar()
                # Estimate scroll position based on button position
                target_scroll = max(0, button_rect.top() - 100)  # Offset for better visibility
                vbar.setValue(target_scroll)
        except Exception as e:
            print(f"Error scrolling to button: {e}")

    def _clear_list(self):
        """Clear all widgets from list"""
        # Remove all widgets except the stretch item if it exists
        while self.list_layout.count() > 0:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.spacerItem():
                # Remove the stretch item if it's the last one
                if self.list_layout.count() == 0:
                    self.list_layout.removeItem(item)

    def _show_no_games_message(self):
        """Show message when no games found"""
        label = QLabel("No games found!\n\nTo add a game, create a folder inside the 'Games' directory\nand place an 'index.html' file inside it.")
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet("color: white; font-size: 18px;")
        self.list_layout.addWidget(label) # Add to the list layout
    
    def set_view_mode(self, is_grid_view):
        """Set the view mode and refresh display if games are loaded"""
        self.is_grid_view = is_grid_view
        # If games are already displayed, refresh the layout
        if self.current_games:
            self.display_games(self.current_games)
    
    def _create_grid_layout(self, games):
        """Create grid layout for games"""
        # Clear existing layout
        self._clear_list()
        
        if not games:
            self._show_no_games_message()
            return
        
        # Create grid layout
        grid_widget = QWidget()
        grid_layout = QGridLayout(grid_widget)
        grid_layout.setSpacing(20)
        grid_layout.setContentsMargins(30, 30, 30, 30)
        
        # Calculate number of columns based on screen width
        # Assuming average game button width is 280px (250 + margins)
        columns = max(1, min(4, (self.width() - 60) // 280))
        
        for i, game in enumerate(games):
            row = i // columns
            col = i % columns
            
            button = GameButton(game)
            button.gameClicked.connect(self.gameSelected.emit)
            grid_layout.addWidget(button, row, col)
        
        self.list_layout.addWidget(grid_widget)
        self.list_layout.addStretch(1)
    
    def _create_vertical_layout(self, games):
        """Create vertical layout for games (original layout)"""
        # Clear existing layout
        self._clear_list()
        
        if not games:
            self._show_no_games_message()
            return
        
        for game in games:
            button = GameButton(game)
            button.gameClicked.connect(self.gameSelected.emit)
            self.list_layout.addWidget(button)
        
        # Add a stretch at the end to push items to the top
        self.list_layout.addStretch(1)


class GamePlayer(QWidget):
    """Widget for playing games with a back button"""
    
    backClicked = pyqtSignal()
    editRequested = pyqtSignal(object)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self.current_game = None
        self.editor_window = None
        self.edit_mode_active = False
        self.setup_shortcuts()
        # Playtime tracking
        self.play_start_time = None
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._update_playtime)
        
        # Instant editor debounced file save timer
        self._save_timer = None
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        QShortcut(QKeySequence(Qt.Key_F12), self, activated=self._toggle_edit_mode)
        QShortcut(QKeySequence(Qt.Key_F9), self, activated=self._cache_selection_instant_edit)
        QShortcut(QKeySequence(Qt.Key_F10), self, activated=self._toggle_gamai_chat)
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=self._toggle_game_overlay)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._exit_edit_mode)
    
    def _setup_ui(self):
        """Setup player UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. Top Bar with Back Button
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #2a2a2a; padding: 5px;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(10, 5, 10, 5)
        
        self.back_button = QPushButton("← Back to Games")
        self.back_button.setFixedSize(150, 30)
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.back_button.clicked.connect(self.backClicked.emit)
        
        self.edit_label = QLabel("F12: Instant Editor | F10: GAMAI | F1: Game Mode | ESC: Exit")
        self.edit_label.setStyleSheet("color: white; font-size: 12px; margin-left: 20px;")
        
        self.save_button = QPushButton("💾 Save")
        self.save_button.setFixedSize(100, 30)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.save_button.clicked.connect(self._save_in_edit_mode)
        self.save_button.setVisible(False)  # Hidden by default
        
        top_bar_layout.addWidget(self.back_button)
        top_bar_layout.addWidget(self.save_button)  # Moved next to back button
        
        # AI Edit button (NEW!)
        self.ai_button = QPushButton("🤖 AI")
        self.ai_button.setFixedSize(80, 30)
        self.ai_button.setCursor(Qt.PointingHandCursor)
        self.ai_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 12px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.ai_button.clicked.connect(self._open_ai_editor)
        top_bar_layout.addWidget(self.ai_button)
        
        top_bar_layout.addWidget(self.edit_label)
        top_bar_layout.addStretch(1)
        
        main_layout.addWidget(top_bar)
        
        # 2. Main Content Area (Game View or Split View)
        self.content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter.setChildrenCollapsible(False)
        
        # IMPORTANT: Reorder to GAMAI (left) | Game (middle) | Editor (right)
        # This ensures instant edit appears on the far right as requested
        
        # GAMAI Chat Panel (left side) - initially hidden
        self.gamai_chat_widget = GamaiChatWidget(context_type="game", parent=self)
        self.gamai_chat_widget.setVisible(False)
        self.content_splitter.addWidget(self.gamai_chat_widget)
        
        # Game View Panel (middle)
        self.game_panel = self._create_game_panel()
        self.content_splitter.addWidget(self.game_panel)
        
        # Editor Panel (right side) - initially hidden
        self.editor_panel = self._create_editor_panel()
        self.editor_panel.setVisible(False)
        self.content_splitter.addWidget(self.editor_panel)
        
        # Track which panels are visible
        self.edit_mode_active = False
        self.gamai_chat_active = False
        
        # Set initial split sizes optimized for 1600x900 resolution
        # Full game view (middle panel gets most space for 1280x720 game)
        # Note: index 0=GAMAI, 1=Game, 2=Editor
        # Optimized for 1600x900: Game gets ~1280px width
        self.content_splitter.setSizes([0, 1280, 0])
        
        main_layout.addWidget(self.content_splitter)
    
    def _create_game_panel(self):
        """Create the game viewing panel"""
        game_area = QWidget()
        game_area_layout = QVBoxLayout(game_area)
        game_area_layout.setAlignment(Qt.AlignCenter)
        
        # Frame for the game to give it a visual boundary
        game_frame = QFrame()
        game_frame.setFrameShape(QFrame.Box)
        game_frame.setFrameShadow(QFrame.Raised)
        game_frame.setStyleSheet("background-color: black; border: 5px solid #3a3a3a;")
        
        # QWebEngineView is the core component for running HTML5 games
        self.webview = QWebEngineView()
        # Set a fixed size for the game view (e.g., 1280x720)
        # This addresses the "buggy" game running by providing a consistent, non-fullscreen viewport.
        self.webview.setFixedSize(1280, 720) 
        self.webview.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        
        game_frame_layout = QVBoxLayout(game_frame)
        game_frame_layout.setContentsMargins(0, 0, 0, 0)
        game_frame_layout.addWidget(self.webview)
        
        game_area_layout.addWidget(game_frame)
        game_area_layout.addStretch(1) # Push game frame to the top center
        
        return game_area
    
    def _create_editor_panel(self):
        """Create the code editor panel for live editing"""
        editor_area = QWidget()
        editor_area_layout = QVBoxLayout(editor_area)
        editor_area_layout.setContentsMargins(10, 10, 10, 10)
        
        # Editor label
        editor_label = QLabel("Code Editor (Live)")
        editor_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        editor_area_layout.addWidget(editor_label)
        
        # Code editor with line numbers (matching full editor style)
        self.live_code_editor = CodeEditorWithLineNumbers()
        # Increased width constraints to prevent line wrapping issues
        self.live_code_editor.setMinimumWidth(400)  # Increased from 250
        self.live_code_editor.setMaximumWidth(800)  # Increased from 400 - more space for long lines
        self.live_code_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                color: white;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 12px;
                selection-background-color: #E5E5E5;
            }
        """)
        self.live_code_editor.textChanged.connect(self._on_live_text_changed)
        
        # Wrap editor in scrollable area for both vertical and horizontal scrolling
        self.editor_scroll_area = QScrollArea()
        self.editor_scroll_area.setWidget(self.live_code_editor)
        self.editor_scroll_area.setWidgetResizable(True)
        # Ensure both scrollbars are available for proper line display
        self.editor_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.editor_scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #3a3a3a;
                width: 16px;
                border-radius: 8px;
            }
            QScrollBar::handle:vertical {
                background-color: #666;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #777;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background-color: #3a3a3a;
                height: 16px;
                border-radius: 8px;
            }
            QScrollBar::handle:horizontal {
                background-color: #666;
                border-radius: 6px;
                min-width: 20px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #777;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
        """)
        
        # Add scroll area to layout
        editor_area_layout.addWidget(self.editor_scroll_area)
        
        return editor_area
    
    def play_game(self, game):
        """Load and play a game with playtime tracking"""
        if not game.is_valid():
            return False
        
        try:
            # Convert local file path to QUrl
            game_url = QUrl.fromLocalFile(str(game.html_path.absolute()))
            self.webview.load(game_url)
            self.current_game = game
            
            # INSTANT EDITOR FIX: Refresh instant editor content when loading new game
            # This ensures the instant editor always shows the current game's code
            if self.edit_mode_active and self.live_code_editor:
                try:
                    if game.html_path.exists():
                        with open(game.html_path, 'r', encoding='utf-8') as f:
                            new_content = f.read()
                        # Update the instant editor with the new game's content
                        self.live_code_editor.setPlainText(new_content)
                        print(f"🔄 Instant editor refreshed with '{game.name}' content")
                except Exception as e:
                    print(f"Warning: Could not refresh instant editor: {e}")
            
            # Start playtime tracking
            self.play_start_time = datetime.now()
            self.play_timer.start(1000)  # Update every second
            
            # Update AI context - user opened game
            GAMAI_CONTEXT.update_context_status("global", f"user opened game '{game.name}'")
            GAMAI_CONTEXT.add_game_context("global", game.name, str(game.folder_path))
            
            return True
        except Exception as e:
            print(f"Error loading game: {e}")
            return False
    
    def stop_game(self):
        """Stop current game and save playtime"""
        # Stop playtime tracking first
        if self.play_start_time and self.current_game:
            self._save_playtime()
        
        # Stop timer
        self.play_timer.stop()
        self.play_start_time = None
        
        # Stop game
        self.webview.setUrl(QUrl("about:blank"))
        current_game_name = self.current_game.name if self.current_game else "unknown"
        self.current_game = None
        
        # Update AI context - user exited game
        GAMAI_CONTEXT.update_context_status("global", f"user exited game '{current_game_name}'")
    
    def _update_playtime(self):
        """Update playtime display (placeholder for future UI integration)"""
        if self.play_start_time and self.current_game:
            elapsed = datetime.now() - self.play_start_time
            # This could update a UI label with elapsed time
            # For now, just keep timer running
    
    def _save_playtime(self):
        """Save accumulated playtime to game manifest"""
        if not self.play_start_time or not self.current_game:
            return
        
        try:
            # Calculate elapsed time
            elapsed = datetime.now() - self.play_start_time
            total_seconds = int(elapsed.total_seconds())
            
            # Convert to minutes, hours, days, weeks, months
            minutes = total_seconds // 60
            hours = minutes // 60
            days = hours // 24
            weeks = days // 7
            months = days // 30  # Approximate
            
            # Calculate remaining time after each unit
            remaining_minutes = minutes % 60
            remaining_hours = hours % 24
            remaining_days = days % 7
            remaining_weeks = weeks % 4
            
            # Update game time_played
            self.current_game.time_played["minutes"] += remaining_minutes
            self.current_game.time_played["hours"] += remaining_hours
            self.current_game.time_played["days"] += remaining_days
            self.current_game.time_played["weeks"] += remaining_weeks
            self.current_game.time_played["months"] += months
            
            # Save to manifest
            self.current_game.save_manifest()
            print(f"Playtime saved: {elapsed.total_seconds():.0f}s")
            
        except Exception as e:
            print(f"Error saving playtime: {e}")
    
    def _toggle_edit_mode(self):
        """Toggle between game view and split-screen live editing"""
        if not self.current_game:
            return
        
        if not self.edit_mode_active:
            # Enter split-screen edit mode
            self._enter_edit_mode()
        else:
            # Exit split-screen edit mode
            self._exit_edit_mode()
    
    def _enter_edit_mode(self):
        """Enter split-screen live editing mode"""
        try:
            # Load current game code into live editor
            if self.current_game and self.current_game.html_path.exists():
                with open(self.current_game.html_path, 'r', encoding='utf-8') as f:
                    self.live_code_editor.setPlainText(f.read())
            
            # Show editor panel (index 2 - far right)
            self.editor_panel.setVisible(True)
            self.save_button.setVisible(True)
            
            # Handle layout based on GAMAI chat state (optimized for 1600x900)
            if self.gamai_chat_active:
                # Both panels open: Scale editor larger for better usability with scrollbars
                # index 0=GAMAI, 1=Game, 2=Editor
                self.content_splitter.setSizes([280, 800, 320])  # Editor: 250px → 320px (larger for scrollbars)
            else:
                # Only edit panel open: optimized for game+edit on right
                # index 0=GAMAI (hidden), 1=Game, 2=Editor
                self.content_splitter.setSizes([0, 1000, 400])  # Game gets 1000px, Editor gets 400px
            
            # Update UI state
            self.edit_mode_active = True
            self.edit_label.setText("INSTANT EDITING - Press F12 to Exit | F10: GAMAI")
            self.edit_label.setStyleSheet("color: #E5E5E5; font-size: 12px; font-weight: bold; margin-left: 20px;")
            
            # Focus on editor
            self.live_code_editor.setFocus()
            
            # Update AI context - user entered instant editor in game mode
            if self.current_game:
                GAMAI_CONTEXT.update_context_status("global", f"user opened instant editor in game mode for game '{self.current_game.name}'")
                GAMAI_CONTEXT.add_game_context("global", self.current_game.name, str(self.current_game.folder_path))
                
                # Refresh editor GAMAI chat to load updated context
                if hasattr(self, 'gamai_chat_widget') and self.gamai_chat_widget:
                    self.gamai_chat_widget.refresh_conversation_history()
            
        except Exception as e:
            print(f"Error entering edit mode: {e}")
    
    def _exit_edit_mode(self):
        """Exit split-screen live editing mode"""
        # Save any changes before exiting
        if self.live_code_editor.toPlainText().strip():
            self._save_in_edit_mode()
        
        # Clean up save timer
        if hasattr(self, '_save_timer') and self._save_timer:
            self._save_timer.stop()
            self._save_timer.deleteLater()
            self._save_timer = None
        
        # Hide editor panel (index 2)
        self.editor_panel.setVisible(False)
        self.save_button.setVisible(False)
        
        # Handle layout based on GAMAI chat state (optimized for 1600x900)
        if self.gamai_chat_active:
            # GAMAI chat still open: optimized for 1280x720 game
            # index 0=GAMAI, 1=Game, 2=Editor (hidden)
            self.content_splitter.setSizes([320, 1280, 0])  # Game gets full 1280px width
        else:
            # No panels open: full game view (1280x720)
            # index 0=GAMAI (hidden), 1=Game, 2=Editor (hidden)
            self.content_splitter.setSizes([0, 1280, 0])  # Game gets full 1280px width
        
        # Update UI state
        self.edit_mode_active = False
        self.edit_label.setText("F12: Instant Editor | F10: GAMAI | ESC: Exit")
        self.edit_label.setStyleSheet("color: white; font-size: 12px; margin-left: 20px;")
        
        # Focus back on game
        self.webview.setFocus()
        
        # Clear selection cache when exiting instant edit mode
        clear_selection_cache()
        
        # Update AI context - user returned to playing after closing instant editor
        if self.current_game:
            GAMAI_CONTEXT.update_context_status("global", f"user returned to playing game '{self.current_game.name}' after closing instant editor")
    
    def _get_selected_text(self, editor_widget):
        """Get selected text from editor widget, handling both QPlainTextEdit and QsciScintilla"""
        if editor_widget is None:
            return "", 0, 0
            
        try:
            # Check if it's a QsciScintilla using type comparison
            if type(editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: get selection using its methods
                if editor_widget.hasSelectedText():
                    selected_text = editor_widget.selectedText()
                    # For QsciScintilla, get line numbers differently
                    line_from, index_from, line_to, index_to = editor_widget.getSelection()
                    start_line = line_from + 1
                    end_line = line_to + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
            else:
                # QPlainTextEdit and similar widgets
                cursor = editor_widget.textCursor()
                if cursor.hasSelection():
                    selected_text = cursor.selectedText()
                    start_line = cursor.blockNumber() + 1
                    end_line = cursor.blockNumber() + 1
                    if cursor.selectionEnd() != cursor.selectionStart():
                        # Multi-line selection
                        temp_cursor = QTextCursor(cursor)
                        temp_cursor.setPosition(cursor.selectionEnd())
                        end_line = temp_cursor.blockNumber() + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
        except Exception as e:
            print(f"Error getting selected text: {e}")
            return "", 0, 0
    
    def _cache_selection_instant_edit(self):
        """Cache current selection from instant editor for AI processing (F9)"""
        if not self.edit_mode_active:
            print("F9: No instant editor active. Press F12 to enter edit mode first.")
            return
        
        # Get selected text from the instant editor
        selected_text, start_line, end_line = self._get_selected_text(self.live_code_editor)
        if selected_text.strip():
            cache_selection(selected_text, start_line, end_line, "instant_edit")
        else:
            print("No text selected in instant editor - selection not cached. Please select code first, then press F9.")
    
    def _toggle_gamai_chat(self):
        """Toggle GAMAI chat panel using F10"""
        if not self.current_game:
            return
        
        if not self.gamai_chat_active:
            # Enter GAMAI chat mode
            self._enter_gamai_chat_mode()
        else:
            # Exit GAMAI chat mode
            self._exit_gamai_chat_mode()
    
    def _enter_gamai_chat_mode(self):
        """Enter GAMAI chat mode"""
        try:
            # Show GAMAI chat panel (index 0)
            self.gamai_chat_widget.setVisible(True)
            
            # Handle layout based on edit mode state (optimized for 1600x900)
            if self.edit_mode_active:
                # Both panels open: 1600x900 total
                # GAMAI|Game|Editor optimized for 1280x720 game display
                # index 0=GAMAI, 1=Game, 2=Editor
                self.content_splitter.setSizes([250, 900, 250])  # Total: 1400 (leaves margin)
            else:
                # Only GAMAI panel open: optimized for 1280x720 game
                # index 0=GAMAI, 1=Game, 2=Editor (hidden)
                self.content_splitter.setSizes([320, 1280, 0])  # Game gets full 1280px width
            
            # Update UI state
            self.gamai_chat_active = True
            self.edit_label.setText("GAMAI CHAT ACTIVE - Press F10 to Close | F12: Instant Editor | ESC: Exit")
            self.edit_label.setStyleSheet("color: #E5E5E5; font-size: 12px; font-weight: bold; margin-left: 20px;")
            
            # Update AI context - user opened GAMAI chat in game mode
            if self.current_game:
                GAMAI_CONTEXT.update_context_status("global", f"user opened GAMAI chat for game '{self.current_game.name}'")
            
        except Exception as e:
            print(f"Error entering GAMAI chat mode: {e}")
    
    def _exit_gamai_chat_mode(self):
        """Exit GAMAI chat mode"""
        try:
            # Hide GAMAI chat panel (index 0)
            self.gamai_chat_widget.setVisible(False)
            
            # Handle layout based on edit mode state (optimized for 1600x900)
            if self.edit_mode_active:
                # Edit panel still open: optimized for game+edit
                # index 0=GAMAI (hidden), 1=Game, 2=Editor
                self.content_splitter.setSizes([0, 1000, 400])  # Game gets 1000px, Editor gets 400px
            else:
                # No panels open: full game view (1280x720)
                # index 0=GAMAI (hidden), 1=Game, 2=Editor (hidden)
                self.content_splitter.setSizes([0, 1280, 0])  # Game gets full 1280px width
            
            # Update UI state
            self.gamai_chat_active = False
            self.edit_label.setText("F12: Instant Editor | F10: GAMAI | ESC: Exit")
            self.edit_label.setStyleSheet("color: white; font-size: 12px; margin-left: 20px;")
            
            # Focus back on game
            self.webview.setFocus()
            
            # Update AI context - user closed GAMAI chat
            if self.current_game:
                GAMAI_CONTEXT.update_context_status("global", f"user closed GAMAI chat for game '{self.current_game.name}'")
            
        except Exception as e:
            print(f"Error exiting GAMAI chat mode: {e}")
    
    def _on_live_text_changed(self):
        """Handle text changes in live editor - update game preview INSTANTLY"""
        if self.edit_mode_active and self.current_game:
            try:
                # Get current code
                html_content = self.live_code_editor.toPlainText()
                
                # INSTANT VISUAL UPDATE: Direct HTML injection for Chrome DevTools-style instant editing
                if hasattr(self.webview, 'setHtml'):
                    # True instant updates - NO file I/O, NO delay, just direct DOM injection
                    self.webview.setHtml(html_content)
                else:
                    # Fallback: reload if setHtml not available (should never happen in gameplay)
                    game_url = QUrl.fromLocalFile(str(self.current_game.html_path.absolute()))
                    self.webview.load(game_url)
                
                # DEBOUNCED FILE SAVE: Save to file for persistence (separate from visual updates)
                self._debounced_file_save(html_content)
            except Exception as e:
                print(f"Error updating live editor: {e}")
    
    def _debounced_file_save(self, content):
        """Debounced file save - prevents excessive I/O while maintaining persistence"""
        # Cancel any existing save timer
        if hasattr(self, '_save_timer') and self._save_timer:
            self._save_timer.stop()
            self._save_timer.deleteLater()
        
        # Create new timer for debounced save
        self._save_timer = QTimer()
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(lambda: self._save_content_to_file(content))
        self._save_timer.start(1000)  # Wait 1 second after last edit before saving
    
    def _save_content_to_file(self, content):
        """Actually save content to file - called by debounced timer"""
        try:
            if self.current_game and self.edit_mode_active:
                with open(self.current_game.html_path, 'w', encoding='utf-8') as f:
                    f.write(content)
        except Exception as e:
            print(f"Error saving file: {e}")
    
    def _save_in_edit_mode(self):
        """Save game in edit mode"""
        try:
            if self.current_game:
                with open(self.current_game.html_path, 'w', encoding='utf-8') as f:
                    f.write(self.live_code_editor.toPlainText())
                
                # Show confirmation
                self.save_button.setText("✅ Saved")
                self.save_button.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                        border: 2px solid #E5E5E5;
                        border-radius: 5px;
                        font-weight: bold;
                        color: white;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                        border: 2px solid #E5E5E5;
                    }
                    QPushButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                            stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                        border: 2px solid #E5E5E5;
                    }
                """)
                
                # Reset button text after 2 seconds
                QTimer.singleShot(2000, lambda: self._reset_save_button())
                
        except Exception as e:
            print(f"Error saving in edit mode: {e}")
            QMessageBox.warning(self, "Error", f"Failed to save: {e}")
    
    def _reset_save_button(self):
        """Reset save button appearance"""
        if self.save_button.isVisible():
            self.save_button.setText("💾 Save")
            self.save_button.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                    border: 2px solid #E5E5E5;
                    border-radius: 5px;
                    font-weight: bold;
                    color: white;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                    border: 2px solid #E5E5E5;
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                    border: 2px solid #E5E5E5;
                }
                QPushButton:disabled {
                    background-color: #2a2a2a;
                    border: 2px solid #555;
                    color: #666;
                }
            """)
    
    def _open_ai_editor(self):
        """Open the AI edition popup with enhanced toggle modes"""
        try:
            # Determine which editor widget to use based on current mode
            editor_widget = None
            if self.edit_mode_active and hasattr(self, 'live_code_editor') and self.live_code_editor:
                # In split-screen mode, use the live editor
                editor_widget = self.live_code_editor
            elif hasattr(self, 'live_code_editor') and self.live_code_editor:
                # Use the live code editor if available (it's always available once created)
                editor_widget = self.live_code_editor
            
            # Check for cached selection first (from F9)
            cache_data = get_cached_selection()
            
            # Always show the enhanced popup to choose mode (even with cached selection)
            # This allows the user to choose between edit_selected and edit_code options
            popup = AIEditionPopup(editor_widget=editor_widget, game=self.current_game, parent=self)
            if popup.exec_() == QDialog.Accepted:
                print("AI editing completed successfully in gameplay")
        except Exception as e:
            QMessageBox.critical(self, "AI Error", f"Failed to open AI editor: {e}")
    
    def _log_ai_edit_activity(self, edit_type, start_line=None, end_line=None):
        """Log AI edit activity for enhanced context awareness"""
        try:
            activity_data = {
                'timestamp': datetime.now().isoformat(),
                'edit_type': edit_type,
                'game_name': self.current_game.name if self.current_game else 'Unknown',
                'start_line': start_line,
                'end_line': end_line
            }
            
            if edit_type == "edit_selected":
                if start_line and end_line:
                    log_entry = f"user edited game '{self.current_game.name}' using edit_selected mode (lines {start_line}-{end_line})"
                else:
                    log_entry = f"user edited game '{self.current_game.name}' using edit_selected mode"
            elif edit_type == "edit_code":
                if start_line and end_line:
                    log_entry = f"user edited game '{self.current_game.name}' using edit_code specific_lines (lines {start_line}-{end_line})"
                else:
                    log_entry = f"user edited game '{self.current_game.name}' using edit_code full_file"
            else:
                log_entry = f"user edited game '{self.current_game.name}' using {edit_type}"
            
            # Add to global GAMAI context for AI awareness
            GAMAI_CONTEXT.add_message("global", "system", f"📝 Activity Log: {log_entry}")
            
            # Store in activity log (you can enhance this to save to file)
            print(f"📝 Activity Log: {log_entry}")
            
            # You can add this to a global activity log system if needed
            if hasattr(self.parent(), 'add_activity_log'):
                self.parent().add_activity_log(log_entry)
                
        except Exception as e:
            print(f"Error logging AI edit activity: {e}")
    
    def keyPressEvent(self, event):
        """Handle keyboard events - F1 for game overlay"""
        if event.key() == Qt.Key_F1:
            if self.current_game:
                self._toggle_game_overlay()
            event.accept()
        else:
            # Pass other events to the parent class
            super().keyPressEvent(event)
    
    def _toggle_game_overlay(self):
        """Toggle game overlay on/off"""
        if hasattr(self, 'game_overlay') and self.game_overlay.isVisible():
            self._hide_game_overlay()
        else:
            self._show_game_overlay()
    
    def _show_game_overlay(self):
        """Show game as overlay covering the entire app window"""
        try:
            # Create overlay if it doesn't exist
            if not hasattr(self, 'game_overlay'):
                self._create_game_overlay()
            
            # Update the overlay with current game
            if self.current_game:
                game_url = QUrl.fromLocalFile(str(self.current_game.html_path.absolute()))
                self.overlay_webview.setUrl(game_url)
            
            # Show the overlay on top
            self.game_overlay.setVisible(True)
            self.game_overlay.raise_()
            self.game_overlay.activateWindow()
            
            # Update UI state
            if hasattr(self, 'edit_label'):
                self.edit_label.setText("F12: Instant Editor | F10: GAMAI | F1: Game Mode | ESC: Exit")
                self.edit_label.setStyleSheet("color: #E5E5E5; font-size: 12px; font-weight: bold; margin-left: 20px;")
            
            print("Game overlay activated - press F1 again to exit")
            
        except Exception as e:
            print(f"Error showing game overlay: {e}")
    
    def _hide_game_overlay(self):
        """Hide game overlay and return to normal view"""
        try:
            if hasattr(self, 'game_overlay'):
                self.game_overlay.setVisible(False)
            
            # Update UI state back to normal
            if hasattr(self, 'edit_label'):
                self.edit_label.setText("F12: Instant Editor | F10: GAMAI | ESC: Exit")
                self.edit_label.setStyleSheet("color: white; font-size: 12px; margin-left: 20px;")
            
            print("Game overlay deactivated")
            
        except Exception as e:
            print(f"Error hiding game overlay: {e}")
    
    def _create_game_overlay(self):
        """Create the game overlay widget"""
        # Get the parent window (GameBox main window)
        parent_window = self.window()
        if not parent_window:
            print("No parent window found for overlay")
            return
        
        # Create overlay widget that covers the entire parent window
        self.game_overlay = QWidget(parent_window)
        self.game_overlay.setVisible(False)
        self.game_overlay.setStyleSheet("background-color: black;")
        
        # Set overlay to cover entire parent window
        self.game_overlay.setGeometry(parent_window.rect())
        
        # Make overlay stay on top
        self.game_overlay.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.game_overlay.setAttribute(Qt.WA_TranslucentBackground, False)
        self.game_overlay.setAttribute(Qt.WA_DeleteOnClose, False)
        
        # Create layout for overlay
        overlay_layout = QVBoxLayout(self.game_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        
        # Add webview to overlay (full size)
        self.overlay_webview = QWebEngineView(self.game_overlay)
        self.overlay_webview.setUrl(QUrl("about:blank"))
        self.overlay_webview.setStyleSheet("background-color: black;")
        
        # Make webview fill the entire overlay
        overlay_layout.addWidget(self.overlay_webview)
        
        # Handle window resize events to keep overlay sized correctly
        # Store the original resize event handler
        if not hasattr(parent_window, '_original_resize_event'):
            parent_window._original_resize_event = parent_window.resizeEvent
        parent_window.resizeEvent = self._on_parent_resize
    
    def _on_parent_resize(self, event):
        """Handle parent window resize to keep overlay sized correctly"""
        try:
            if hasattr(self, 'game_overlay') and self.game_overlay.isVisible():
                # Resize overlay to match parent window
                self.game_overlay.setGeometry(self.window().rect())
        except Exception as e:
            print(f"Error handling parent resize: {e}")
        # Call original resize event
        if hasattr(self.window(), '_original_resize_event'):
            self.window()._original_resize_event(event)

class SyntaxPanel(QWidget):
    """Panel showing syntax errors and suggestions"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
    
    def _setup_ui(self):
        """Setup syntax panel UI"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        
        # Title
        title_label = QLabel("🔧 Syntax & Errors")
        title_label.setStyleSheet("color: #E5E5E5; font-size: 14px; font-weight: bold;")
        layout.addWidget(title_label)
        
        # Syntax results area
        self.results_area = QTextBrowser()
        self.results_area.setStyleSheet("""
            QTextBrowser {
                background-color: #2a2a2a;
                color: #E5E5E5;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
                padding: 10px;
                font-size: 12px;
            }
        """)
        layout.addWidget(self.results_area)
        
        # Initialize with empty message
        self.set_results([])
    
    def set_results(self, results):
        """Set syntax checking results"""
        if not results:
            self.results_area.setHtml("""
                <div style="text-align: center; color: #666; font-style: italic;">
                    ✅ No syntax errors detected<br>
                    <small>Start typing to see live validation</small>
                </div>
            """)
        else:
            html = "<div style='font-family: monospace;'>"
            for result in results:
                severity_color = "#E5E5E5" if result.get('type') == 'error' else "#E5E5E5"
                html += f"""
                <div style="margin-bottom: 8px; padding: 5px; background-color: #333; border-left: 3px solid {severity_color};">
                    <strong style="color: {severity_color};">{result.get('type', 'Error').upper()}</strong><br>
                    <span style="color: #ccc;">Line {result.get('line', '?')}: {result.get('message', 'Unknown error')}</span>
                </div>
                """
            html += "</div>"
            self.results_area.setHtml(html)


class EnhancedCodeEditorWidget(QWidget):
    """Enhanced code editor with syntax highlighting and 3-panel layout"""
    
    gameSaved = pyqtSignal(object)
    finishRequested = pyqtSignal()
    
    def __init__(self, game, game_service, parent=None):
        super().__init__(parent)
        self.game = game
        self.game_service = game_service
        self.unsaved_changes = False
        self.auto_refresh_timer = None
        self.is_running = False
        self.syntax_enabled = False
        self._setup_ui()
        self._load_game_code()
        self._setup_shortcuts()
        self._setup_auto_refresh()
    
    def _setup_ui(self):
        """Setup enhanced editor UI"""
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Enhanced toolbar with syntax toggle
        toolbar = QWidget()
        toolbar.setFixedHeight(50)
        toolbar.setStyleSheet("background-color: #2a2a2a; border-bottom: 1px solid #3a3a3a;")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(10, 0, 10, 0)
        
        # Run button
        self.run_button = QPushButton("▶ Run Game")
        self.run_button.setFixedSize(120, 35)
        self.run_button.setCursor(Qt.PointingHandCursor)
        self.run_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
        """)
        self.run_button.clicked.connect(self._run_game)
        
        # Stop button
        self.stop_button = QPushButton("⏹ Stop")
        self.stop_button.setFixedSize(100, 35)
        self.stop_button.setCursor(Qt.PointingHandCursor)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }

            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.stop_button.clicked.connect(self._stop_game)
        
        # Save button
        self.save_button = QPushButton("💾 Save")
        self.save_button.setFixedSize(100, 35)
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.save_button.clicked.connect(self._save_game)
        
        # Syntax toggle button (NEW!)
        self.syntax_button = QPushButton("📝 Syntax")
        self.syntax_button.setFixedSize(120, 35)
        self.syntax_button.setCursor(Qt.PointingHandCursor)
        self.syntax_button.setCheckable(True)
        self.syntax_button.setStyleSheet("""
            QPushButton {
                background-color: #666;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
            QPushButton:checked {
                background-color: #E5E5E5;
            }
        """)
        self.syntax_button.toggled.connect(self._toggle_syntax_panel)
        
        # Manifest editor button (NEW!)
        self.manifest_button = QPushButton("📋 Manifest")
        self.manifest_button.setFixedSize(130, 35)
        self.manifest_button.setCursor(Qt.PointingHandCursor)
        self.manifest_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                color: white;
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1a1a, stop:0.3 #1a1a1a, stop:0.7 #2a2a2a, stop:1 #1a1a1a);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #3a3a3a, stop:1 #2a2a2a);
                border: 2px solid #E5E5E5;
            }
        """)
        self.manifest_button.clicked.connect(self._open_manifest_editor)
        
        # Icon management button (NEW!)
        self.icon_button = QPushButton("🖼️ Icon")
        self.icon_button.setFixedSize(120, 35)
        self.icon_button.setCursor(Qt.PointingHandCursor)
        self.icon_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.icon_button.clicked.connect(self._open_icon_options)
        
        # Finish button
        self.finish_button = QPushButton("✕ Finish")
        self.finish_button.setFixedSize(100, 35)
        self.finish_button.setCursor(Qt.PointingHandCursor)
        self.finish_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        self.finish_button.clicked.connect(self._finish_editing)
        
        toolbar_layout.addWidget(self.run_button)
        toolbar_layout.addWidget(self.stop_button)
        toolbar_layout.addWidget(self.save_button)
        toolbar_layout.addStretch()
        toolbar_layout.addWidget(self.syntax_button)
        toolbar_layout.addWidget(self.manifest_button)
        toolbar_layout.addWidget(self.icon_button)
        
        # AI Edit button (NEW!)
        self.ai_button = QPushButton("🤖 AI")
        self.ai_button.setFixedSize(100, 35)
        self.ai_button.setCursor(Qt.PointingHandCursor)
        self.ai_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        self.ai_button.clicked.connect(self._open_ai_editor)
        toolbar_layout.addWidget(self.ai_button)
        
        toolbar_layout.addWidget(self.finish_button)
        
        main_layout.addWidget(toolbar)
        
        # Enhanced splitter for 3-panel layout
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        
        # Code editor panel (left panel)
        self.editor_widget = self._create_code_editor_panel()
        
        # Preview panel (middle/right panel)
        self.preview_widget = self._create_preview_panel()
        
        # Syntax panel (rightmost panel) - initially hidden
        self.syntax_panel = SyntaxPanel()
        self.syntax_panel.setVisible(False)
        
        # GAMAI chat widget (replaces syntax panel when F10 pressed)
        self.gamai_chat_widget = GamaiChatWidget(context_type="editor", parent=self)
        self.gamai_chat_widget.setVisible(False)
        self.gamai_chat_active = False  # Track which panel is active
        
        # Add panels to splitter
        self.splitter.addWidget(self.editor_widget)
        self.splitter.addWidget(self.preview_widget)
        self.splitter.addWidget(self.syntax_panel)  # Will be replaced by GAMAI when active
        
        # Use proportional sizing instead of absolute values
        # Calculate based on typical window size and adapt proportionally
        self.splitter.setStretchFactor(0, 3)  # Editor: 3 parts
        self.splitter.setStretchFactor(1, 5)  # Preview: 5 parts
        self.splitter.setStretchFactor(2, 2)  # Syntax: 2 parts
        
        # Set initial sizes based on proportions (total: 10 parts)
        self.splitter.setSizes([300, 500, 200])  # These will be scaled by Qt
        
        main_layout.addWidget(self.splitter)
        
        # Initialize preview
        self._update_preview()
    
    def _create_code_editor_panel(self):
        """Create code editor panel with syntax highlighting"""
        editor_widget = QWidget()
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(10, 10, 5, 10)
        
        # Editor label
        editor_label = QLabel("HTML + CSS + JavaScript")
        editor_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        editor_layout.addWidget(editor_label)
        
        # Enhanced code editor with syntax highlighting
        if HAS_QSCINTILLA:
            self.code_editor = QsciScintilla()
            self._setup_syntax_highlighting()
        else:
            # Fallback to regular text editor
            self.code_editor = QPlainTextEdit()
            self.code_editor.setMinimumSize(600, 400)  # Set minimum size for readability
            self.code_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.code_editor.setStyleSheet("""
                QPlainTextEdit {
                    background-color: #1e1e1e;
                    color: #E5E5E5;
                    border: 1px solid #3a3a3a;
                    border-radius: 5px;
                    font-family: 'Courier New', monospace;
                    font-size: 13px;
                    padding: 15px;
                }
                QPlainTextEdit:focus {
                    border-color: #E5E5E5;
                }
            """)
        
        self.code_editor.textChanged.connect(self._on_text_changed)
        editor_layout.addWidget(self.code_editor)
        
        return editor_widget
    
    def _setup_syntax_highlighting(self):
        """Setup enhanced syntax highlighting with eye-friendly dark theme"""
        # Set lexer to HTML (will handle embedded CSS/JS)
        self.lexer = QsciLexerHTML()
        self.lexer.setFont(QFont("Courier New", 12))
        
        # Enhanced Eye-Friendly Dark Theme Colors
        # Background: Soft dark gray instead of pure black
        # Text: Light gray for reduced eye strain
        # Syntax: High contrast but comfortable colors
        
        # Eye-friendly light theme syntax colors
        self.lexer.setColor(QColor("#2c2c2c"), QsciLexerHTML.Default)  # Main text - dark gray
        self.lexer.setColor(QColor("#0066cc"), QsciLexerHTML.Tag)  # HTML tags - professional blue
        self.lexer.setColor(QColor("#E5E5E5"), QsciLexerHTML.Attribute)  # Attributes - orange
        self.lexer.setColor(QColor("#6a9955"), QsciLexerHTML.HTMLComment)  # Comments - green
        self.lexer.setColor(QColor("#E5E5E5"), QsciLexerHTML.CDATA)  # CDATA - red-brown
        
        # Apply lexer to editor
        self.code_editor.setLexer(self.lexer)
        
        # Enhanced Editor Appearance with Eye-Friendly Light Theme
        self.code_editor.setStyleSheet("""
            QsciScintilla {
                background-color: #E5E5E5;  /* Light gray - comfortable for eyes */
                color: #2c2c2c;             /* Dark gray text - high contrast */
                border: 1px solid #E5E5E5;  /* Light border */
                border-radius: 6px;
                font-family: 'Courier New', 'Consolas', monospace;
                font-size: 14px;            /* Comfortable font size */
                line-height: 1.4;
                selection-background-color: #E5E5E5; /* Light blue selection */
            }
            QsciScintilla:focus {
                border-color: #E5E5E5;
            }
            /* Selection highlighting */
            QsciScintilla::selection {
                background-color: #264f78;
                color: white;
            }
        """)
        
        # Enable useful editor features
        self.code_editor.setCaretLineVisible(True)
        self.code_editor.setCaretLineBackgroundColor(QColor("#E5E5E5"))  # Light theme current line highlight
        self.code_editor.setIndentationWidth(4)
        self.code_editor.setIndentationsUseTabs(False)
        
        # Enhanced margins for line numbers with better colors
        self.code_editor.setMarginType(0, QsciScintilla.NumberMargin)
        self.code_editor.setMarginWidth(0, "00000")
        
        # Style line numbers area with compatible method only
        self.code_editor.setMarginBackgroundColor(0, QColor("#E5E5E5"))
        
        # Enable code folding with better colors
        self.code_editor.setFolding(QsciScintilla.BoxedTreeFoldStyle)
        
        # Enable bracket matching with better colors
        self.code_editor.setBraceMatching(QsciScintilla.SloppyBraceMatch)
        
        # Enhanced bracket matching colors for light theme
        self.code_editor.setMatchedBraceBackgroundColor(QColor("#d4edda"))
        self.code_editor.setMatchedBraceForegroundColor(QColor("#155724"))
        self.code_editor.setUnmatchedBraceBackgroundColor(QColor("#E5E5E5"))
        self.code_editor.setUnmatchedBraceForegroundColor(QColor("#721c24"))
        
        # Enable auto-completion
        self.code_editor.setAutoCompletionSource(QsciScintilla.AcsAll)
        self.code_editor.setAutoCompletionThreshold(2)

    
    def _create_preview_panel(self):
        """Create preview panel"""
        preview_widget = QWidget()
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(5, 10, 10, 10)
        
        # Preview label
        self.preview_label = QLabel("Live Preview (800x600 container, 1920x1080 game with scrollbars) - Press F1 for Fullscreen")
        self.preview_label.setStyleSheet("color: white; font-size: 14px; font-weight: bold; margin-bottom: 5px;")
        preview_layout.addWidget(self.preview_label)
        
        # Preview web view with scroll area
        self.preview_webview = QWebEngineView()
        self.preview_webview.setFixedSize(1920, 1080)  # High resolution game 1920x1080
        self.preview_webview.setStyleSheet("""
            QWebEngineView {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
            }
        """)
        
        # Create scroll area for the preview webview
        self.preview_scroll_area = QScrollArea()
        self.preview_scroll_area.setWidget(self.preview_webview)
        self.preview_scroll_area.setWidgetResizable(False)  # Keep webview at fixed size
        self.preview_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.preview_scroll_area.setFixedSize(800, 600)  # Container size 800x600
        self.preview_scroll_area.viewport().setAttribute(Qt.WA_Hover, True)  # Enable mouse hover for scrolling
        self.preview_scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #2a2a2a;
                border: 1px solid #3a3a3a;
                border-radius: 5px;
            }
            QScrollArea:focus {
                border: 1px solid #E5E5E5;
            }
            QScrollBar:vertical {
                background-color: #3a3a3a;
                width: 16px;
                border-radius: 8px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background-color: #555555;
                border-radius: 8px;
                min-height: 20px;
                margin: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #E5E5E5;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
            QScrollBar:horizontal {
                background-color: #3a3a3a;
                height: 16px;
                border-radius: 8px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background-color: #555555;
                border-radius: 8px;
                min-width: 20px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #E5E5E5;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
            }
        """)
        
        preview_layout.addWidget(self.preview_scroll_area)
        
        return preview_widget
    
    def _toggle_syntax_panel(self, enabled):
        """Toggle syntax panel visibility and adjust layout"""
        self.syntax_enabled = enabled
        
        # If GAMAI chat is active, switch back to syntax mode first
        if self.gamai_chat_active and enabled:
            self._show_syntax_panel()
            return
        
        if enabled:
            # Show syntax panel and use 3-panel layout
            self.syntax_panel.setVisible(True)
            self.syntax_panel.setMinimumWidth(250)
            self.syntax_panel.setMaximumWidth(400)
            self.splitter.setSizes([350, 550, 300])
        else:
            # Hide syntax panel and use 2-panel layout
            self.syntax_panel.setVisible(False)
            self.syntax_panel.setMinimumWidth(0)
            self.syntax_panel.setMaximumWidth(0)
            self.splitter.setSizes([600, 600])
    
    def _toggle_gamai_chat(self):
        """Toggle between syntax panel and GAMAI chat using F10"""
        if self.gamai_chat_active:
            # Currently showing GAMAI, switch back to syntax
            self._show_syntax_panel()
        else:
            # Currently showing syntax (or nothing), switch to GAMAI
            self._show_gamai_chat()
    
    def _show_gamai_chat(self):
        """Show GAMAI chat in the right panel"""
        # Hide syntax panel
        self.syntax_panel.setVisible(False)
        self.syntax_enabled = False
        self.syntax_button.setChecked(False)
        
        # Show GAMAI chat
        self.splitter.replaceWidget(self.splitter.indexOf(self.syntax_panel), self.gamai_chat_widget)
        self.gamai_chat_widget.setVisible(True)
        self.gamai_chat_widget.setMinimumWidth(200)
        self.gamai_chat_widget.setMaximumWidth(400)
        self.gamai_chat_active = True
        
        # Use proportional sizing: Editor:Preview:GAMAI = 3:5:2 (total 10 parts)
        self.splitter.setSizes([300, 500, 200])
    
    def _show_syntax_panel(self):
        """Show syntax panel (hide GAMAI chat)"""
        # Hide GAMAI chat
        self.gamai_chat_widget.setVisible(False)
        self.gamai_chat_active = False
        
        # Show syntax panel if syntax is enabled
        if self.syntax_enabled:
            self.splitter.replaceWidget(self.splitter.indexOf(self.gamai_chat_widget), self.syntax_panel)
            self.syntax_panel.setVisible(True)
            # Use proportional sizing: Editor:Preview:Syntax = 3:5:2 (total 10 parts)
            self.splitter.setSizes([300, 500, 200])
        else:
            # Syntax disabled, remove right panel and use 2-panel layout
            self.splitter.replaceWidget(self.splitter.indexOf(self.gamai_chat_widget), self.syntax_panel)
            self.syntax_panel.setVisible(False)
            # Use 2-panel layout: Editor:Preview = 1:1 (total 2 parts)
            self.splitter.setSizes([500, 500])
    
    def _setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        QShortcut(QKeySequence(Qt.Key_F5), self, activated=self._run_game)
        QShortcut(QKeySequence(Qt.Key_F9), self, activated=self._update_preview_and_cache_selection)
        QShortcut(QKeySequence(Qt.Key_F10), self, activated=self._toggle_gamai_chat)
        QShortcut(QKeySequence(Qt.Key_F1), self, activated=self._toggle_game_overlay)
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self._finish_editing)
        # New shortcut for syntax toggle
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=lambda: self.syntax_button.toggle())
    
    def _setup_auto_refresh(self):
        """Setup automatic preview refresh"""
        self.auto_refresh_timer = QTimer(self)
        self.auto_refresh_timer.timeout.connect(self._update_preview)
        self.auto_refresh_timer.start(100)
    
    def _on_text_changed(self):
        """Handle text changes"""
        self.unsaved_changes = True
        
        # Update syntax checking if enabled
        if self.syntax_enabled and HAS_QSCINTILLA:
            self._check_syntax()
    
    def _check_syntax(self):
        """Perform enhanced syntax checking for HTML/CSS/JS"""
        try:
            content = self.code_editor.text() if hasattr(self.code_editor, 'text') else self.code_editor.toPlainText()
            
            results = []
            lines = content.split('\n')
            
            # AGGRESSIVE HTML validation - catch obvious errors
            for i, line in enumerate(lines, 1):
                line_stripped = line.strip()
                
                # Basic HTML tag validation
                if '<' in line and '>' not in line and not line_stripped.startswith('<!--'):
                    results.append({
                        'type': 'error',
                        'line': i,
                        'message': 'Unclosed HTML tag or missing >'
                    })
                
                # Check for malformed tags (extra < without >)
                tag_count = line.count('<')
                close_count = line.count('>')
                if tag_count > close_count and tag_count > 0:
                    results.append({
                        'type': 'error',
                        'line': i,
                        'message': f'Malformed HTML tag (found {tag_count} < but {close_count} >)'
                    })
                
                # Simple quote validation
                if ('"' in line and line.count('"') % 2 != 0) or ("'" in line and line.count("'") % 2 != 0):
                    results.append({
                        'type': 'error',
                        'line': i,
                        'message': 'Unclosed quote in this line'
                    })
                
                # Check for unclosed brackets in CSS
                if '{' in line or '}' in line:
                    open_braces = line.count('{')
                    close_braces = line.count('}')
                    if open_braces != close_braces and open_braces > 0:
                        results.append({
                            'type': 'error',
                            'line': i,
                            'message': 'Unbalanced CSS braces'
                        })
                
                # Check for unmatched parentheses (common JS error)
                if '(' in line or ')' in line:
                    open_parens = line.count('(')
                    close_parens = line.count(')')
                    if open_parens != close_parens and open_parens > 0:
                        results.append({
                            'type': 'warning',
                            'line': i,
                            'message': 'Possible unmatched parentheses'
                        })
            
            # Enhanced CSS validation
            css_results = self._check_css_syntax(content)
            results.extend(css_results)
            
            # Enhanced JavaScript validation
            js_results = self._check_javascript_syntax(content)
            results.extend(js_results)
            
            # Print debug info
            print(f"[DEBUG] Syntax check found {len(results)} issues")
            for result in results:
                print(f"[DEBUG] Line {result['line']}: {result['message']}")
            
            # Update syntax panel
            self.syntax_panel.set_results(results)
            
        except Exception as e:
            print(f"Syntax checking error: {e}")
            # Show error in panel
            self.syntax_panel.set_results([{
                'type': 'error',
                'line': 0,
                'message': f'Syntax checker error: {str(e)}'
            }])
    
    def _check_css_syntax(self, content):
        """Check for CSS syntax errors"""
        results = []
        lines = content.split('\n')
        in_style = False
        brace_count = 0
        
        for i, line in enumerate(lines, 1):
            # Track style blocks
            if '<style>' in line.lower():
                in_style = True
                # Check if style tag is properly closed in same line
                if '</style>' not in line.lower():
                    # Look ahead for closing tag
                    next_lines = lines[i:i+20]  # Look ahead 20 lines
                    if not any('</style>' in next_line.lower() for next_line in next_lines):
                        results.append({
                            'type': 'error',
                            'line': i,
                            'message': 'CSS: Opening <style> tag not closed'
                        })
            elif '</style>' in line.lower():
                in_style = False
            
            if in_style:
                # Check CSS bracket matching
                brace_count += line.count('{') - line.count('}')
                
                # Check for incomplete CSS property (property: value missing)
                if ':' in line and not line.strip().endswith(';') and '{' not in line:
                    if not line.strip().startswith('/*') and '*/' not in line:
                        results.append({
                            'type': 'warning',
                            'line': i,
                            'message': 'CSS property may be missing semicolon'
                        })
        
        # Check for unclosed CSS braces at the end
        if brace_count > 0:
            results.append({
                'type': 'error',
                'line': len(lines),
                'message': f'CSS: {brace_count} unclosed CSS block(s)'
            })
        
        return results
    
    def _check_javascript_syntax(self, content):
        """Check for JavaScript syntax errors"""
        results = []
        lines = content.split('\n')
        in_script = False
        
        for i, line in enumerate(lines, 1):
            # Track script blocks
            if '<script' in line.lower():
                in_script = True
            elif '</script>' in line.lower():
                in_script = False
            
            if in_script:
                # Check for unmatched parentheses in script
                if line.strip():
                    # Basic parenthesis matching
                    paren_depth = 0
                    bracket_depth = 0
                    brace_depth = 0
                    
                    for char in line:
                        if char == '(':
                            paren_depth += 1
                        elif char == ')':
                            paren_depth -= 1
                        elif char == '[':
                            bracket_depth += 1
                        elif char == ']':
                            bracket_depth -= 1
                        elif char == '{':
                            brace_depth += 1
                        elif char == '}':
                            brace_depth -= 1
                    
                    if paren_depth != 0 and paren_depth < 0:
                        results.append({
                            'type': 'error',
                            'line': i,
                            'message': 'JavaScript: Extra closing parenthesis'
                        })
                    if bracket_depth != 0 and bracket_depth < 0:
                        results.append({
                            'type': 'error',
                            'line': i,
                            'message': 'JavaScript: Extra closing bracket'
                        })
                    
                # Check for common JS syntax errors
                if 'function(' in line and not line.strip().endswith(')'):
                    if '{' not in line and i < len(lines):
                        # Check next line for opening brace
                        next_line = lines[i] if i < len(lines) else ''
                        if '{' not in next_line:
                            results.append({
                                'type': 'warning',
                                'line': i,
                                'message': 'JavaScript: Function may be incomplete'
                            })
        
        return results
    
    def _get_html_content(self):
        """Get current HTML content from editor"""
        if hasattr(self.code_editor, 'text'):
            return self.code_editor.text()
        else:
            return self.code_editor.toPlainText()
    
    def _set_html_content(self, content):
        """Set HTML content in editor"""
        if hasattr(self.code_editor, 'text'):
            self.code_editor.setText(content)
        else:
            self.code_editor.setPlainText(content)
    
    def _update_preview(self):
        """Update live preview - optimized version"""
        if self.is_running:
            return
        
        html_content = self._get_html_content()
        
        # Smart change detection
        if hasattr(self, 'last_preview_content') and html_content == self.last_preview_content:
            return
        self.last_preview_content = html_content
        
        if html_content.strip():
            # Direct content injection - NO FILE I/O, NO WINDOW REFRESH
            self.preview_webview.setHtml(html_content)
    
    def _update_preview_and_cache_selection(self):
        """Update preview and cache current selection for AI processing"""
        # First, cache the selection if there is one
        self._cache_selection()
        
        # Then update preview as usual
        self._update_preview()
    
    def _load_game_code(self):
        """Load game code into editor"""
        try:
            with open(self.game.html_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self._set_html_content(content)
            self.unsaved_changes = False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load game: {e}")
    
    def _save_game(self):
        """Save game code with confirmation and visual feedback"""
        try:
            # Show save confirmation dialog
            reply = QMessageBox.question(
                self,
                "Save Game",
                f"Save changes to '{self.game.name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                content = self._get_html_content()
                with open(self.game.html_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                
                # Increment edit count and save to manifest
                self.game.edits += 1
                self.game.save_manifest()
                
                self.unsaved_changes = False
                
                # Visual feedback
                self._show_save_feedback()
                
                self.gameSaved.emit(self.game)
            # If No, do nothing (user cancelled)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save game: {e}")
    
    def _show_save_feedback(self):
        """Show visual feedback for successful save"""
        # Save button color change to darker blue
        self.save_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        
        # Change text to "Saved" 
        original_text = self.save_button.text()
        self.save_button.setText("✅ Saved")
        
        # Reset after 2 seconds
        QTimer.singleShot(2000, lambda: self._reset_save_button(original_text))
    
    def _reset_save_button(self, original_text):
        """Reset save button to original state"""
        if self.save_button.isVisible():
            self.save_button.setText(original_text)
            self.save_button.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                    border: 2px solid #E5E5E5;
                    border-radius: 5px;
                    font-size: 13px;
                    font-weight: bold;
                    color: white;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                    border: 2px solid #E5E5E5;
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                        stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                    border: 2px solid #E5E5E5;
                }
            """)
    
    def _run_game(self):
        """Run the game"""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Run anyway?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        
        self.is_running = True
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.save_button.setEnabled(False)
        
        # Stop auto-refresh during game execution
        if self.auto_refresh_timer:
            self.auto_refresh_timer.stop()
        
        # Load and run the game
        try:
            content = self._get_html_content()
            if not content.strip():
                QMessageBox.warning(self, "Empty Game", "No game code to run.")
                return
            
            self.preview_webview.setHtml(content)
            self.preview_label.setText("🎮 Game Running...")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to run game: {e}")
            self.is_running = False
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.save_button.setEnabled(True)
    
    def _stop_game(self):
        """Stop the running game"""
        self.is_running = False
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.save_button.setEnabled(True)
        self.preview_label.setText("Live Preview")
        
        # Resume auto-refresh
        if self.auto_refresh_timer:
            self.auto_refresh_timer.start(100)
        
        # Update preview
        self._update_preview()
    
    def keyPressEvent(self, event):
        """Handle keyboard events - F1 for game overlay"""
        if event.key() == Qt.Key_F1:
            if hasattr(self, 'game_overlay') and self.game_overlay.isVisible():
                self._hide_game_overlay()
            else:
                self._show_game_overlay()
            event.accept()
        else:
            # Pass other events to the parent class
            super().keyPressEvent(event)
    
    def _toggle_game_overlay(self):
        """Toggle game overlay on/off"""
        if hasattr(self, 'game_overlay') and self.game_overlay.isVisible():
            self._hide_game_overlay()
        else:
            self._show_game_overlay()
    
    def _show_game_overlay(self):
        """Show game as overlay covering the entire app window"""
        try:
            # Create overlay if it doesn't exist
            if not hasattr(self, 'game_overlay'):
                self._create_game_overlay()
            
            # Get parent window
            parent_window = self.window()
            if not parent_window:
                print("No parent window found for overlay")
                return
            
            # Hide scroll area (keep webview in scroll area intact)
            self.preview_scroll_area.setVisible(False)
            self.game_overlay.setVisible(True)
            
            # Update overlay geometry to cover entire app window
            self.game_overlay.setGeometry(parent_window.rect())
            
            # Resize overlay webview to fill entire window
            if hasattr(self, 'overlay_webview'):
                self.overlay_webview.setGeometry(0, 0, self.game_overlay.width(), self.game_overlay.height())
                self.overlay_webview.setVisible(True)
                
                # Load the same game content as the preview webview into the overlay
                if hasattr(self, 'preview_webview'):
                    try:
                        # Get the current HTML content from preview webview
                        self.preview_webview.page().toHtml(self._load_overlay_content)
                    except Exception as e:
                        print(f"Error loading overlay content: {e}")
            
            # Make overlay stay on top
            self.game_overlay.raise_()
            self.game_overlay.activateWindow()
            
            print("Game overlay activated in full editor - press F1 again to exit")
            
        except Exception as e:
            print(f"Error showing game overlay: {e}")
    
    def _load_overlay_content(self, html_content):
        """Callback to load content into overlay webview"""
        try:
            if hasattr(self, 'overlay_webview'):
                self.overlay_webview.setHtml(html_content)
        except Exception as e:
            print(f"Error loading overlay content: {e}")
    
    def _hide_game_overlay(self):
        """Hide game overlay"""
        try:
            if hasattr(self, 'game_overlay'):
                # Hide overlay and show scroll area again
                self.game_overlay.setVisible(False)
                self.preview_scroll_area.setVisible(True)
            
            print("Game overlay deactivated")
            
        except Exception as e:
            print(f"Error hiding game overlay: {e}")
    
    def _create_game_overlay(self):
        """Create the game overlay widget"""
        # Get the parent window (GameBox main window)
        parent_window = self.window()
        if not parent_window:
            print("No parent window found for overlay")
            return
        
        # Create overlay widget that covers the entire parent window
        self.game_overlay = QWidget(parent_window)
        self.game_overlay.setVisible(False)
        self.game_overlay.setStyleSheet("background-color: black;")
        
        # Set overlay to cover entire parent window
        self.game_overlay.setGeometry(parent_window.rect())
        
        # Create layout for overlay
        overlay_layout = QVBoxLayout(self.game_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create new webview specifically for overlay (fullscreen)
        self.overlay_webview = QWebEngineView()
        overlay_layout.addWidget(self.overlay_webview)
        
        # Set webview to fill entire overlay
        self.overlay_webview.setGeometry(0, 0, self.game_overlay.width(), self.game_overlay.height())
        
        # Style the overlay webview
        self.overlay_webview.setStyleSheet("""
            QWebEngineView {
                background-color: #2a2a2a;
                border: none;
            }
        """)
        
        # Make overlay stay on top
        self.game_overlay.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.game_overlay.setAttribute(Qt.WA_TranslucentBackground, False)
        self.game_overlay.setAttribute(Qt.WA_DeleteOnClose, False)
    
    def resizeEvent(self, event):
        """Handle window resize events - keep overlay in sync"""
        super().resizeEvent(event)
        
        # If overlay is active, resize webview to fit new window size
        if hasattr(self, 'game_overlay') and self.game_overlay.isVisible():
            parent_window = self.window()
            if parent_window:
                self.game_overlay.setGeometry(parent_window.rect())
                self.preview_webview.setGeometry(0, 0, self.game_overlay.width(), self.game_overlay.height())
    
    def _finish_editing(self):
        """Finish editing and return to main view"""
        if self.unsaved_changes:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Save before exiting?",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel
            )
            if reply == QMessageBox.Yes:
                self._save_game()
            elif reply == QMessageBox.Cancel:
                return
        
        # Clean up
        if self.auto_refresh_timer:
            self.auto_refresh_timer.stop()
            self.auto_refresh_timer = None
        
        if hasattr(self, 'last_preview_content'):
            delattr(self, 'last_preview_content')
        
        # Clear selection cache when exiting editor
        clear_selection_cache()
        
        self.finishRequested.emit()
    
    def _cache_selection(self):
        """Cache current selection for AI processing (F9)"""
        try:
            selected_text, start_line, end_line = self._get_selected_text(self.code_editor)
            if selected_text.strip():
                cache_selection(selected_text, start_line, end_line, "main_editor")
                print(f"Selection cached: {len(selected_text)} chars from line {start_line} to {end_line}")
            else:
                print("No text selected - nothing to cache. Please select code first, then press F9.")
        except Exception as e:
            print(f"Error caching selection: {e}")
    
    def _get_selected_text(self, editor_widget):
        """Get selected text from editor widget, handling both QPlainTextEdit and QsciScintilla"""
        if editor_widget is None:
            return "", 0, 0
            
        try:
            # Check if it's a QsciScintilla using type comparison
            if type(editor_widget).__name__ == 'QsciScintilla':
                # QsciScintilla: get selection using its methods
                if editor_widget.hasSelectedText():
                    selected_text = editor_widget.selectedText()
                    # For QsciScintilla, get line numbers differently
                    line_from, index_from, line_to, index_to = editor_widget.getSelection()
                    start_line = line_from + 1
                    end_line = line_to + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
            else:
                # QPlainTextEdit and similar widgets
                cursor = editor_widget.textCursor()
                if cursor.hasSelection():
                    selected_text = cursor.selectedText()
                    start_line = cursor.blockNumber() + 1
                    end_line = cursor.blockNumber() + 1
                    if cursor.selectionEnd() != cursor.selectionStart():
                        # Multi-line selection
                        temp_cursor = QTextCursor(cursor)
                        temp_cursor.setPosition(cursor.selectionEnd())
                        end_line = temp_cursor.blockNumber() + 1
                    return selected_text, start_line, end_line
                else:
                    return "", 0, 0
        except Exception as e:
            print(f"Error getting selected text: {e}")
            return "", 0, 0
    
    def _open_manifest_editor(self):
        """Open the manifest editor dialog with choice between Manual and AI options"""
        from PyQt5.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QPushButton
        
        # Create custom choice dialog
        choice_dialog = QDialog(self)
        choice_dialog.setWindowTitle("📋 Manifest Editor")
        choice_dialog.setFixedSize(400, 250)
        choice_dialog.setModal(True)
        
        # Set dialog background styling
        choice_dialog.setStyleSheet("""
            QDialog {
                background-color: #1a1a1a;
                color: white;
            }
        """)
        
        layout = QVBoxLayout(choice_dialog)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # Title
        title_label = QLabel("📋 Manifest Editor")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel("Choose how you want to edit the manifest:")
        desc_label.setAlignment(Qt.AlignCenter)
        desc_label.setStyleSheet("color: #E5E5E5; font-size: 14px; margin-bottom: 20px;")
        layout.addWidget(desc_label)
        
        # Button layout
        button_layout = QHBoxLayout()
        button_layout.setSpacing(20)
        button_layout.addStretch()
        
        # Manual button
        manual_btn = QPushButton("Manual")
        manual_btn.setFixedSize(110, 40)
        manual_btn.setCursor(Qt.PointingHandCursor)
        manual_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                color: white;
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1a1a, stop:0.3 #1a1a1a, stop:0.7 #2a2a2a, stop:1 #1a1a1a);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #3a3a3a, stop:1 #2a2a2a);
                border: 2px solid #E5E5E5;
            }
        """)
        
        # AI button
        ai_btn = QPushButton("AI")
        ai_btn.setFixedSize(110, 40)
        ai_btn.setCursor(Qt.PointingHandCursor)
        ai_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                color: white;
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1a1a1a, stop:0.3 #1a1a1a, stop:0.7 #2a2a2a, stop:1 #1a1a1a);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2a2a2a, stop:0.3 #2a2a2a, stop:0.7 #3a3a3a, stop:1 #2a2a2a);
                border: 2px solid #E5E5E5;
            }
        """)
        
        button_layout.addWidget(manual_btn)
        button_layout.addWidget(ai_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        # Button connections
        def on_manual_clicked():
            choice_dialog.done(1)  # Return 1 for manual
            
        def on_ai_clicked():
            choice_dialog.done(2)  # Return 2 for AI
            
        manual_btn.clicked.connect(on_manual_clicked)
        ai_btn.clicked.connect(on_ai_clicked)
        
        result = choice_dialog.exec_()
        
        if result == 1:  # Manual
            # Open the existing manifest editor
            dialog = ManifestEditorDialog(self.game, self)
            if dialog.exec_() == QDialog.Accepted:
                # Optional: Update any UI elements that show game info
                # For now, the manifest editor handles all updates internally
                pass
        elif result == 2:  # AI
            # Open the AI manifest editor
            ai_dialog = AIManifestEditorDialog(self.game, self)
            if ai_dialog.exec_() == QDialog.Accepted:
                # AI manifest editing was successful
                print("AI manifest editing completed successfully")
    
    def _open_icon_options(self):
        """Open the icon options dialog"""
        dialog = IconOptionsDialog(self.game, self.game_service, self)
        dialog.exec_()
    
    def _open_ai_editor(self):
        """Open the AI edition popup"""
        try:
            # Create and show the AI edition popup
            popup = AIEditionPopup(editor_widget=self.code_editor, game=self.game, parent=self)
            if popup.exec_() == QDialog.Accepted:
                # AI editing was successful, optionally update the UI
                print("AI editing completed successfully")
        except Exception as e:
            QMessageBox.critical(self, "AI Error", f"Failed to open AI editor: {e}")
            pass
    
    def contextMenuEvent(self, event):
        """Handle right-click context menu for AI code editing"""
        # Get the text cursor and check if text is selected
        cursor = self.code_editor.textCursor()
        if cursor.hasSelection():
            # Text is selected, show context menu with AI option
            menu = QMenu(self)
            
            # Standard options
            cut_action = menu.addAction("Cut")
            copy_action = menu.addAction("Copy")
            paste_action = menu.addAction("Paste")
            menu.addSeparator()
            
            # AI option - only show when text is selected
            ai_action = menu.addAction("🤖 AI Edit Selected")
            ai_action.setToolTip("Use AI to edit the selected code")
            
            # Get the action that was selected
            action = menu.exec_(event.globalPos())
            
            if action == ai_action:
                # Open AI edit dialog
                self._open_ai_edit_dialog()
        else:
            # No text selected, show standard menu without AI option
            menu = QMenu(self)
            menu.addAction("Cut").setEnabled(False)
            menu.addAction("Copy").setEnabled(False)
            menu.addAction("Paste")
            menu.exec_(event.globalPos())

class CodeEditorWithLineNumbers(QPlainTextEdit):
    """Custom QPlainTextEdit with line numbers - matching full editor style"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_number_area = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        
        # DISABLE LINE WRAPPING - Critical for accurate line counting in edit_code tool
        # This prevents long lines from wrapping and ensures 1 actual line = 1 displayed line
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        
        # Ensure horizontal scrollbar is always available for long lines
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.update_line_number_area_width(0)
        self.highlight_current_line()
    
    def line_number_area_width(self):
        digits = 1
        max_num = max(1, self.blockCount())
        while max_num >= 10:
            max_num //= 10
            digits += 1
        
        space = 3 + self.fontMetrics().width('9') * digits
        return space
    
    def update_line_number_area_width(self, _):
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)
    
    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_number_area.scroll(0, dy)
        else:
            self.line_number_area.update(0, rect.y(), rect.width(), rect.height())
        
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)
    
    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.line_number_area.setGeometry(QRect(cr.left(), cr.top(), self.line_number_area_width(), cr.height()))
    
    def paintEvent(self, event):
        super().paintEvent(event)
    
    def highlight_current_line(self):
        extraSelections = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection()
            lineColor = QColor(50, 50, 50).lighter(160)
            selection.format.setBackground(lineColor)
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extraSelections.append(selection)
        self.setExtraSelections(extraSelections)


class LineNumberArea(QWidget):
    """Line number area widget"""
    
    def __init__(self, editor):
        super().__init__(editor)
        self.code_editor = editor
    
    def sizeHint(self):
        return QSize(self.code_editor.line_number_area_width(), 0)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#E5E5E5"))
        
        block = self.code_editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.code_editor.blockBoundingGeometry(block).translated(self.code_editor.contentOffset()).top())
        bottom = top + int(self.code_editor.blockBoundingRect(block).height())
        
        font = self.code_editor.font()
        painter.setFont(font)
        painter.setPen(QColor("#333333"))
        
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(0, top, self.width() - 6, self.code_editor.fontMetrics().height(),
                               Qt.AlignRight | Qt.AlignTop, number)
            
            block = block.next()
            top = bottom
            bottom = top + int(self.code_editor.blockBoundingRect(block).height())
            block_number += 1


def fade_widget_in(widget, duration=200):
    """Smooth fade-in animation for any widget"""
    if not widget or widget.isVisible():
        return
    
    # Create opacity effect
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    
    # Start from invisible
    effect.setOpacity(0.0)
    widget.show()
    
    # Animate to fully visible
    animation = QPropertyAnimation(effect, b"opacity")
    animation.setDuration(duration)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.start()


def fade_widget_out(widget, duration=200, hide_after=True):
    """Smooth fade-out animation for any widget"""
    if not widget or not widget.isVisible():
        return
    
    # Get or create opacity effect
    effect = widget.graphicsEffect()
    if not effect or not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    
    # Start from fully visible
    effect.setOpacity(1.0)
    
    # Animate to invisible
    animation = QPropertyAnimation(effect, b"opacity")
    animation.setDuration(duration)
    animation.setStartValue(1.0)
    animation.setEndValue(0.0)
    animation.setEasingCurve(QEasingCurve.InCubic)
    
    if hide_after:
        animation.finished.connect(lambda: widget.hide())
    
    animation.start()
    return animation


def slide_fade_widget_in(widget, direction='bottom', duration=300):
    """Slide and fade animation for widget entrance"""
    if not widget or widget.isVisible():
        return
    
    # Position animation
    pos_anim = QPropertyAnimation(widget, b"pos")
    pos_anim.setDuration(duration)
    pos_anim.setEasingCurve(QEasingCurve.OutCubic)
    
    # Opacity animation
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    effect.setOpacity(0.0)
    
    # Get starting and ending positions
    start_pos = widget.pos()
    end_pos = widget.pos()
    widget_offset = 20
    
    if direction == 'bottom':
        end_pos.setY(end_pos.y() + widget_offset)
    elif direction == 'top':
        end_pos.setY(end_pos.y() - widget_offset)
    elif direction == 'left':
        end_pos.setX(end_pos.x() - widget_offset)
    elif direction == 'right':
        end_pos.setX(end_pos.x() + widget_offset)
    
    # Setup animations
    pos_anim.setStartValue(end_pos)
    pos_anim.setEndValue(start_pos)
    
    opacity_anim = QPropertyAnimation(effect, b"opacity")
    opacity_anim.setDuration(duration)
    opacity_anim.setStartValue(0.0)
    opacity_anim.setEndValue(1.0)
    opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
    
    # Start both animations
    widget.show()
    pos_anim.start()
    opacity_anim.start()
    
    return pos_anim, opacity_anim


def slide_fade_widget_out(widget, direction='bottom', duration=300, hide_after=True):
    """Slide and fade animation for widget exit"""
    if not widget or not widget.isVisible():
        return
    
    # Position animation
    pos_anim = QPropertyAnimation(widget, b"pos")
    pos_anim.setDuration(duration)
    pos_anim.setEasingCurve(QEasingCurve.InCubic)
    
    # Opacity animation
    effect = widget.graphicsEffect()
    if not effect or not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    
    effect.setOpacity(1.0)
    
    # Get starting and ending positions
    start_pos = widget.pos()
    end_pos = widget.pos()
    widget_offset = 20
    
    if direction == 'bottom':
        end_pos.setY(end_pos.y() + widget_offset)
    elif direction == 'top':
        end_pos.setY(end_pos.y() - widget_offset)
    elif direction == 'left':
        end_pos.setX(end_pos.x() - widget_offset)
    elif direction == 'right':
        end_pos.setX(end_pos.x() + widget_offset)
    
    # Setup animations
    pos_anim.setStartValue(start_pos)
    pos_anim.setEndValue(end_pos)
    
    opacity_anim = QPropertyAnimation(effect, b"opacity")
    opacity_anim.setDuration(duration)
    opacity_anim.setStartValue(1.0)
    opacity_anim.setEndValue(0.0)
    opacity_anim.setEasingCurve(QEasingCurve.InCubic)
    
    # Chain animations
    if hide_after:
        opacity_anim.finished.connect(lambda: widget.hide())
    
    pos_anim.start()
    opacity_anim.start()
    
    return pos_anim, opacity_anim


class GameBox(QMainWindow):
    """Main application window (GameBox Launcher)"""
    
    def __init__(self):
        super().__init__()
        
        # Services
        self.game_service = GameService()
        self.games = []
        
        # State
        self.is_fullscreen = True
        
        # Search functionality state
        self.original_games = []
        self.current_filtered_games = []
        self.is_filtered = False
        
        # View toggle state (session-only, resets on restart)
        self.is_grid_view = False  # Default is vertical layout
        
        # Setup
        self._setup_window()
        self._setup_ui()
        
        # Load games in background
        self._load_games_async()
        
        # Set initial AI context - user is in main menu
        GAMAI_CONTEXT.update_context_status("global", "user is in main menu")
        
        # Ensure icon visibility in taskbar after window is shown
        QTimer.singleShot(100, self._ensure_taskbar_icon)
    
    def _ensure_taskbar_icon(self):
        """Ensure the icon appears properly in taskbar"""
        try:
            # Get the current window icon and re-apply it
            icon = self.windowIcon()
            if not icon.isNull():
                self.setWindowIcon(icon)
                print("✅ Taskbar icon verification completed")
            else:
                # Try to reload the icon
                if Path(resource_path("logo.png")).exists():
                    icon = QIcon(resource_path("logo.png"))
                    self.setWindowIcon(icon)
                    print("✅ Reloaded icon for taskbar visibility")
        except Exception as e:
            print(f"⚠️ Could not ensure taskbar icon: {e}")
    
    def _setup_window(self):
        """Configure main window"""
        self.setWindowTitle("GameBox")
        
        # Set window icon with enhanced support
        def setup_window_icon():
            """Set window icon with fallbacks"""
            icon_paths = [
                resource_path("logo.png"),
                resource_path("GameBox.ico"),
                resource_path("GameBox.png"),
                "logo.png", "GameBox.ico", "GameBox.png"  # Fallback for dev mode
            ]
            icon = None
            
            # Try to load icon with multiple fallbacks
            for path in icon_paths:
                try:
                    if Path(path).exists():
                        icon = QIcon(path)
                        print(f"✅ Found window icon at: {path}")
                        break
                except Exception as e:
                    print(f"⚠️ Failed to load window icon from {path}: {e}")
                    continue
            
            if icon is not None:
                self.setWindowIcon(icon)
                # Also set as default for child widgets
                self.setWindowIcon(icon)
                print("✅ Window icon set successfully")
            else:
                print("⚠️ No window icon could be loaded")
        
        setup_window_icon()
        
        # Requirement: runs in full screen by default
        self.showFullScreen()
        
        # Global stylesheet for the application including QMessageBox and custom dialogs
        self.setStyleSheet("""
            /* Main window background */
            background-color: #0a0a0a;
            
            /* Global QMessageBox styling for all confirmation/info boxes */
            QMessageBox {
                background-color: #1a1a1a;
                color: #E5E5E5;
            }
            
            QMessageBox QLabel {
                color: #E5E5E5;
                font-size: 14px;
            }
            
            QMessageBox QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #E5E5E5;
                border-radius: 4px;
                color: #E5E5E5;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 16px;
                min-width: 80px;
            }
            
            QMessageBox QPushButton:hover {
                background-color: #3a3a3a;
                border: 2px solid #E5E5E5;
            }
            
            QMessageBox QPushButton:pressed {
                background-color: #1a1a1a;
                border: 2px solid #E5E5E5;
            }
            
            QMessageBox QPushButton:focus {
                border: 2px solid #E5E5E5;
                outline: none;
            }
            
            /* Global QDialog styling for custom confirmation dialogs */
            QDialog {
                background-color: #1a1a1a;
                color: #E5E5E5;
            }
            
            QDialog QLabel {
                color: #E5E5E5;
                font-size: 14px;
            }
            
            QDialog QPushButton {
                background-color: #2a2a2a;
                border: 2px solid #E5E5E5;
                border-radius: 4px;
                color: #E5E5E5;
                font-size: 13px;
                font-weight: bold;
                padding: 8px 16px;
                min-width: 80px;
            }
            
            QDialog QPushButton:hover {
                background-color: #3a3a3a;
                border: 2px solid #E5E5E5;
            }
            
            QDialog QPushButton:pressed {
                background-color: #1a1a1a;
                border: 2px solid #E5E5E5;
            }
            
            QDialog QPushButton:focus {
                border: 2px solid #E5E5E5;
                outline: none;
            }
        """)
    
    def _setup_ui(self):
        """Setup user interface"""
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        
        # Stack layout to switch between list and player
        self.main_layout = QVBoxLayout(central)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        # Top bar with create button
        self._setup_top_bar()
        
        # Game list (Launcher view)
        self.game_list = GameList()
        self.game_list.gameSelected.connect(self._on_game_selected)
        self.main_layout.addWidget(self.game_list)
        
        # Game player (Game view)
        self.game_player = GamePlayer()
        self.game_player.backClicked.connect(self._return_to_list)
        self.game_player.setVisible(False) # Hidden initially
        self.main_layout.addWidget(self.game_player)
        
        # Code editor (Editor view)
        self.editor_widget = None  # Will be created when needed
        self.editor_view_container = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_view_container)
        self.editor_layout.setContentsMargins(0, 0, 0, 0)
        self.editor_view_container.setVisible(False) # Hidden initially
        self.main_layout.addWidget(self.editor_view_container)
    
    def _setup_top_bar(self):
        """Setup top bar with create button"""
        top_bar = QWidget()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background-color: #2a2a2a; border-bottom: 2px solid #3a3a3a;")
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(20, 10, 20, 10)
        
        # Create button
        self.create_button = QPushButton("+")
        self.create_button.setFixedSize(50, 40)
        self.create_button.setCursor(Qt.PointingHandCursor)
        self.create_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 24px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.create_button.clicked.connect(self._show_create_options)
        
        # Search button
        self.search_button = QPushButton("🔍")
        self.search_button.setFixedSize(50, 40)
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        self.search_button.clicked.connect(self._open_search_engine)
        
        # Create logo + title layout (logo on left, text on right)
        title_layout = QHBoxLayout()
        title_layout.setSpacing(8)  # Small spacing between logo and text
        
        # Add logo
        try:
            logo_path = resource_path("logo.png")
            if Path(logo_path).exists():
                logo_pixmap = QPixmap(logo_path)
            # Scale logo to fit in top bar (typical height is around 40-50px)
            scaled_logo = logo_pixmap.scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label = QLabel()
            logo_label.setPixmap(scaled_logo)
            logo_label.setStyleSheet("border: none; background: transparent;")
            title_layout.addWidget(logo_label)
            print("✅ Logo added to top bar")
        except Exception as e:
            print(f"⚠️ Could not load logo for top bar: {e}")
            # Fallback: add a small spacer if logo fails
            title_layout.addSpacing(32)
        
        # Add title text
        title_label = QLabel("GameBox")
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold;")
        title_layout.addWidget(title_label)
        
        # Create a widget to hold the title layout
        title_widget = QWidget()
        title_widget.setLayout(title_layout)
        
        top_bar_layout.addWidget(self.create_button)
        top_bar_layout.addWidget(self.search_button)
        
        # View Toggle Button
        self.view_toggle_button = ViewToggleButton(self.is_grid_view, self)
        self.view_toggle_button.viewChanged.connect(self._on_view_changed)
        top_bar_layout.addWidget(self.view_toggle_button)
        
        # AI Assistant Button (GAMAI)
        self.ai_button = QPushButton("✨")
        self.ai_button.setFixedSize(50, 40)
        self.ai_button.setCursor(Qt.PointingHandCursor)
        self.ai_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 20px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
        """)
        self.ai_button.clicked.connect(self._open_gamai_assistant)
        top_bar_layout.addWidget(self.ai_button)
        
        # Spacer to push buttons to the right side of the bar
        top_bar_layout.addStretch()
        
        # Show All Games button (initially hidden)
        self.show_all_button = QPushButton("📋 Show All Games")
        self.show_all_button.setFixedSize(180, 40)  # Increased width for better text visibility
        self.show_all_button.setCursor(Qt.PointingHandCursor)
        self.show_all_button.setVisible(False)  # Hidden until search is used
        self.show_all_button.clicked.connect(self._show_all_games)
        self.show_all_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 12px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        top_bar_layout.addWidget(self.show_all_button)
        
        top_bar_layout.addWidget(title_widget)
        top_bar_layout.addStretch()
        
        self.main_layout.addWidget(top_bar)
    
    def _show_create_options(self):
        """Show create options dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Create or Edit")
        dialog.setFixedSize(350, 400)  # Increased size for better button fit and text visibility
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("What would you like to do?")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: white; margin: 10px;")
        layout.addWidget(title_label)
        
        # Buttons
        create_button = QPushButton("+ Create New Game")
        create_button.setFixedSize(300, 45)
        create_button.setCursor(Qt.PointingHandCursor)
        create_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        create_button.clicked.connect(lambda: (dialog.close(), self._create_new_game()))
        
        import_button = QPushButton("📁 Import Game")
        import_button.setFixedSize(300, 45)
        import_button.setCursor(Qt.PointingHandCursor)
        import_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        import_button.clicked.connect(lambda: (dialog.close(), self._show_import_options()))
        
        export_button = QPushButton("📦 Export Game")
        export_button.setFixedSize(300, 45)
        export_button.setCursor(Qt.PointingHandCursor)
        export_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        export_button.clicked.connect(lambda: (dialog.close(), self._export_game()))
        layout.addWidget(export_button)
        
        edit_button = QPushButton("✎ Edit Existing Game")
        edit_button.setFixedSize(300, 45)
        edit_button.setCursor(Qt.PointingHandCursor)
        edit_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        edit_button.clicked.connect(lambda: (dialog.close(), self._edit_existing_game()))
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(300, 35)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        cancel_button.clicked.connect(dialog.close)
        
        layout.addWidget(create_button)
        layout.addWidget(import_button)
        layout.addWidget(edit_button)
        layout.addWidget(cancel_button)
        
        dialog.setStyleSheet("background-color: #1a1a1a;")
        dialog.exec_()

    def _show_import_options(self):
        """Show import options dialog"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Import Options")
        dialog.setFixedSize(350, 250)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)
        
        # Title
        title_label = QLabel("How would you like to import?")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: white; margin: 10px;")
        layout.addWidget(title_label)
        
        # Index button
        index_button = QPushButton("📋 Index")
        index_button.setFixedSize(300, 45)
        index_button.setCursor(Qt.PointingHandCursor)
        index_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        index_button.clicked.connect(lambda: (dialog.close(), self._import_from_index()))
        
        # Zip button
        zip_button = QPushButton("📦 Zip")
        zip_button.setFixedSize(300, 45)
        zip_button.setCursor(Qt.PointingHandCursor)
        zip_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 5px;
                color: white;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        zip_button.clicked.connect(lambda: (dialog.close(), self._import_from_zip()))
        
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(300, 35)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        cancel_button.clicked.connect(dialog.close)
        
        layout.addWidget(index_button)
        layout.addWidget(zip_button)
        layout.addWidget(cancel_button)
        
        dialog.setStyleSheet("background-color: #1a1a1a;")
        dialog.exec_()

    def _import_from_index(self):
        """Import game using existing index system"""
        self._import_game()

    def _import_from_zip(self):
        """Import games from ZIP file with comprehensive validation"""
        # Open file dialog for ZIP selection
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ZIP Game File",
            "",
            "ZIP Files (*.zip);;All Files (*)"
        )
        
        if not file_path:
            return  # User cancelled
        
        try:
            # Validate that it's actually a ZIP file
            if not zipfile.is_zipfile(file_path):
                QMessageBox.warning(
                    self,
                    "Invalid File",
                    "Selected file is not a valid ZIP file."
                )
                return
            
            # Import games from ZIP
            success_count, error_count, errors = self._process_zip_import(file_path)
            
            # Show results to user
            if success_count > 0:
                if error_count == 0:
                    message = f"Successfully imported {success_count} game(s) from ZIP file!"
                else:
                    message = f"Imported {success_count} game(s) with {error_count} error(s):\n\n" + "\n".join(errors)
                
                QMessageBox.information(self, "Import Complete", message)
            else:
                QMessageBox.warning(
                    self,
                    "Import Failed",
                    f"No games could be imported from the ZIP file.\n\nErrors:\n" + "\n".join(errors)
                )
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Import Error",
                f"An unexpected error occurred during import:\n{str(e)}"
            )

    def _process_zip_import(self, zip_path):
        """Process ZIP file and import games based on structure"""
        success_count = 0
        error_count = 0
        errors = []
        
        # Create temporary extraction directory
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Extract ZIP file
                with zipfile.ZipFile(zip_path, 'r') as zip_file:
                    zip_file.extractall(temp_dir)
                
                # Analyze ZIP structure
                games_to_import = self._analyze_zip_structure(temp_dir)
                
                if not games_to_import:
                    errors.append("No valid games found in ZIP file")
                    return success_count, error_count, errors
                
                # Process each game
                for game_info in games_to_import:
                    try:
                        game_folder = self._create_game_from_extracted_files(game_info, temp_dir)
                        if game_folder:
                            success_count += 1
                        else:
                            error_count += 1
                            errors.append(f"Failed to create game: {game_info.get('name', 'Unknown')}")
                    except Exception as e:
                        error_count += 1
                        errors.append(f"Error processing game: {str(e)}")
                
            except Exception as e:
                errors.append(f"Failed to extract ZIP file: {str(e)}")
        
        return success_count, error_count, errors

    def _analyze_zip_structure(self, extracted_path):
        """Analyze ZIP structure to determine import scenario and identify games"""
        games = []
        extracted_path = Path(extracted_path)
        
        # Get all items in the root
        root_items = [item for item in extracted_path.iterdir()]
        
        if not root_items:
            return games
        
        # Separate folders and files
        folders = [item for item in root_items if item.is_dir()]
        files = [item for item in root_items if item.is_file()]
        
        # Scenario 3: Multiple folders (multiple games)
        if len(folders) > 1:
            for folder in folders:
                game_info = self._analyze_game_folder(folder)
                if game_info:
                    games.append(game_info)
        
        # Scenario 2: Single folder (one game)
        elif len(folders) == 1:
            game_folder = folders[0]
            game_info = self._analyze_game_folder(game_folder)
            if game_info:
                games.append(game_info)
        
        # Scenario 1: Files directly in root (one game)
        elif files:
            game_info = self._analyze_root_files(extracted_path)
            if game_info:
                games.append(game_info)
        
        return games

    def _analyze_game_folder(self, folder_path):
        """Analyze a game folder structure - include all files and subdirectories"""
        # Get all files and subdirectories recursively
        all_items = []
        for item in folder_path.rglob('*'):
            if item.is_file():
                all_items.append(item)
        return self._analyze_game_files(all_items, folder_path.name)

    def _analyze_root_files(self, root_path):
        """Analyze files directly in ZIP root - include all files and subdirectories"""
        # Get all files recursively from root
        all_files = []
        for item in root_path.rglob('*'):
            if item.is_file():
                all_files.append(item)
        return self._analyze_game_files(all_files, "root")

    def _analyze_game_files(self, files, source_name):
        """Analyze game files and validate structure"""
        file_names = [f.name for f in files]
        
        # Look for HTML files
        html_files = [f for f in file_names if f.lower().endswith(('.html', '.htm'))]
        
        if not html_files:
            return None  # No HTML files, not a valid game
        
        # Check for multiple HTML files without index.html
        if len(html_files) > 1 and 'index.html' not in file_names:
            # This will be handled as an error during game creation
            return {
                'name': source_name,
                'files': files,
                'has_error': True,
                'error_type': 'multiple_html_no_index'
            }
        
        # Determine main HTML file
        if 'index.html' in file_names:
            main_html = 'index.html'
        elif len(html_files) == 1:
            main_html = html_files[0]  # Will be renamed to index.html
        else:
            # Multiple HTML files with index.html present
            main_html = 'index.html'
        
        # Check for icon
        has_valid_icon = 'icon.png' in file_names
        
        return {
            'name': source_name,
            'files': files,
            'main_html': main_html,
            'has_icon': has_valid_icon,
            'has_error': False
        }

    def _create_game_from_extracted_files(self, game_info, temp_dir):
        """Create a new game from extracted and validated files"""
        # Generate random game name
        game_name = self._generate_random_name()
        
        # Check for errors
        if game_info.get('has_error'):
            error_type = game_info.get('error_type')
            if error_type == 'multiple_html_no_index':
                raise ValueError("Multiple HTML files detected without index.html")
        
        # Create game directory
        game_dir = self.game_service.games_folder / game_name
        game_dir.mkdir(exist_ok=True)
        
        try:
            # Process files - now includes subdirectories
            files = game_info['files']
            main_html = game_info.get('main_html', 'index.html')
            
            for file_path in files:
                if file_path.is_file():
                    file_name = file_path.name
                    
                    # Calculate relative path to preserve directory structure
                    try:
                        # Get relative path from temp_dir
                        relative_path = file_path.relative_to(temp_dir)
                        # Get the parts after the game folder
                        relative_parts = relative_path.parts[1:]  # Skip the game folder name
                        
                        # Handle HTML files
                        if file_name.lower().endswith(('.html', '.htm')):
                            if file_name != 'index.html':
                                # Rename to index.html and put in root
                                target_path = game_dir / 'index.html'
                                shutil.copy2(file_path, target_path)
                            else:
                                # Already named index.html, put in root
                                target_path = game_dir / 'index.html'
                                shutil.copy2(file_path, target_path)
                        
                        # Handle icon files
                        elif file_name.lower() == 'icon.png':
                            if self._validate_icon_resolution(file_path):
                                target_path = game_dir / 'icon.png'
                                shutil.copy2(file_path, target_path)
                            # Skip if invalid resolution
                        
                        # Handle other files (assets) - preserve directory structure
                        else:
                            # Create target directory if it doesn't exist
                            if relative_parts:
                                target_dir = game_dir / Path(*relative_parts[:-1])
                                target_dir.mkdir(parents=True, exist_ok=True)
                                target_path = game_dir / Path(*relative_parts)
                            else:
                                # File is directly in game folder
                                target_path = game_dir / file_name
                            
                            shutil.copy2(file_path, target_path)
                            
                    except ValueError:
                        # Fallback for files that can't calculate relative path
                        if file_name.lower().endswith(('.html', '.htm')):
                            if file_name != 'index.html':
                                target_path = game_dir / 'index.html'
                                shutil.copy2(file_path, target_path)
                            else:
                                target_path = game_dir / 'index.html'
                                shutil.copy2(file_path, target_path)
                        elif file_name.lower() == 'icon.png':
                            if self._validate_icon_resolution(file_path):
                                target_path = game_dir / 'icon.png'
                                shutil.copy2(file_path, target_path)
                        else:
                            target_path = game_dir / file_name
                            shutil.copy2(file_path, target_path)
            
            # Create manifest.json
            self._create_game_manifest(game_dir, game_name)
            
            # Add game to games list
            self._add_game_to_list(game_name)
            
            return game_dir
            
        except Exception as e:
            # Clean up on failure
            if game_dir.exists():
                shutil.rmtree(game_dir)
            raise e

    def _validate_icon_resolution(self, icon_path):
        """Validate that icon.png is exactly 200x200 pixels"""
        try:
            from PIL import Image
            with Image.open(icon_path) as img:
                return img.size == (200, 200)
        except Exception:
            return False

    def _create_game_manifest(self, game_dir, game_name):
        """Create manifest.json for the game"""
        manifest = {
            "name": game_name,
            "version": "1.0.0",
            "type": "2D",
            "players": "1",
            "main_categories": [
                "Tools"
            ],
            "sub_categories": [],
            "time_played": {
                "minutes": 0,
                "hours": 0,
                "days": 0,
                "weeks": 0,
                "months": 0
            },
            "edits": 0,
            "played_times": 0,
            "icon": "icon.png",
            "created": datetime.now().isoformat()
        }
        
        manifest_path = game_dir / 'manifest.json'
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4)

    def _generate_random_name(self):
        """Generate a random 10-character name using letters and numbers"""
        characters = string.ascii_letters + string.digits
        while True:
            random_name = ''.join(random.choice(characters) for _ in range(10))
            # Check if name already exists in current games
            if not any(game.name == random_name for game in self.games):
                return random_name

    def _add_game_to_list(self, game_name):
        """Add the newly created game to the games list and refresh display"""
        # Create game object using GameInfo class (following existing pattern)
        game_dir = self.game_service.games_folder / game_name
        if game_dir.exists():
            # Load the game using the existing GameService pattern
            game_info = self.game_service._load_game(game_dir)
            if game_info and game_info.is_valid():
                self.games.append(game_info)
                
                # Refresh the game list display
                self.game_list.display_games(self.games)

    def _open_search_engine(self):
        """Open search engine dialog"""
        dialog = SearchEngineDialog(self.games, self)
        if dialog.exec_() == QDialog.Accepted:
            filtered_games = dialog.get_filtered_games()
            self.game_list.display_games(filtered_games)
            # Store original games for "Show All Games" functionality
            self.original_games = self.games.copy()
            self.current_filtered_games = filtered_games
            # Show the "Show All Games" button
            self.show_all_button.setVisible(True)
            self.is_filtered = True
    
    def _show_all_games(self):
        """Show all games, clearing any filters"""
        if self.original_games:
            self.game_list.display_games(self.original_games)
            self.show_all_button.setVisible(False)
            self.is_filtered = False
    
    def _open_gamai_assistant(self):
        """Open GAMAI main menu options"""
        # Check if API key is configured
        if not is_gamai_configured():
            # Show API key setup dialog
            api_dialog = GamaiApiKeyDialog(self)
            if api_dialog.exec_() == QDialog.Accepted:
                # API key was saved successfully, now show main menu
                self._show_gamai_main_menu()
            else:
                return
        else:
            # API key exists, show main menu
            self._show_gamai_main_menu()
    
    def _show_gamai_main_menu(self):
        """Show GAMAI main menu dialog"""
        try:
            menu_dialog = GamaiMainMenuDialog(self)
            if menu_dialog.exec_() == QDialog.Accepted:
                option = menu_dialog.get_selected_option()
                if option == "chat":
                    self._open_gamai_chat()
                elif option == "create_game":
                    # Show Two Creation Options Dialog
                    dialog = AICreationOptionsDialog(self)
                    if dialog.exec_() == QDialog.Accepted:
                        creation_type = dialog.get_selected_type()
                        if creation_type == "surprise":
                            self._open_surprise_game_creation()
                        elif creation_type == "oneshot":
                            self._open_one_shot_game_creation()
                        elif creation_type == "foryou":
                            self._open_foryou_game_creation()
                elif option == "import_game":
                    self._open_ai_import_game()
        except Exception as e:
            QMessageBox.critical(self, "GAMAI Error", f"Failed to open AI assistant: {str(e)}")
    
    def _open_ai_import_game(self):
        """Open AI-powered game import dialog"""
        try:
            # Check if API key is configured for AI functionality
            if not is_gamai_configured():
                QMessageBox.warning(
                    self, 
                    "API Key Required", 
                    "AI-powered import requires a Gemini API key. Please configure it first."
                )
                return
            
            # Open AI import dialog
            import_dialog = AIGameImportDialog(self)
            if import_dialog.exec_() == QDialog.Accepted:
                # Import was successful (handled in dialog)
                # Reload games and update display
                updated_games = self.game_service.discover_games()
                self.games = updated_games
                # Update display
                if hasattr(self, 'is_filtered') and self.is_filtered and hasattr(self, 'current_filtered_games'):
                    if self.current_filtered_games:
                        self.game_list.display_games(self.current_filtered_games)
                    else:
                        self.game_list.display_games(updated_games)
                else:
                    self.game_list.display_games(updated_games)
                
                # Get the imported game name from dialog and highlight it
                imported_game_name = import_dialog.imported_game_name
                if imported_game_name:
                    # Schedule highlighting after UI update
                    QTimer.singleShot(500, lambda: self.game_list.highlight_game(imported_game_name))
                
                # Show success message
                QMessageBox.information(
                    self,
                    "Import Complete",
                    "🎮 Game imported successfully using AI analysis!\n\n"
                    "The game has been automatically categorized and added to your collection.\n"
                    "You can now play it or edit it using the available options."
                )
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to open AI import dialog: {str(e)}")
    
    def _open_gamai_chat(self):
        """Open GAMAI chat - now uses the same embedded system as F10"""
        try:
            # Use the same toggle system as F10 for consistency
            self.game_list._toggle_gamai_chat()
        except Exception as e:
            QMessageBox.critical(self, "GAMAI Error", f"Failed to open AI assistant: {str(e)}")
    
    def _on_view_changed(self, is_grid_view):
        """Handle view mode changes"""
        self.is_grid_view = is_grid_view
        # Update the game list view mode
        self.game_list.set_view_mode(is_grid_view)
        # Refresh the current display
        if self.is_filtered and self.current_filtered_games:
            self.game_list.display_games(self.current_filtered_games)
        else:
            self.game_list.display_games(self.games)
    
    def _open_one_shot_game_creation(self):
        """Open One-Shot AI game creation dialog"""
        try:
            # Check if API key is configured for AI functionality
            if not is_gamai_configured():
                QMessageBox.warning(
                    self, 
                    "API Key Required", 
                    "AI-powered game generation requires a Gemini API key. Please configure it first."
                )
                return
            
            dialog = OneShotGameDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                # Game creation is handled within the dialog
                pass
        except Exception as e:
            QMessageBox.critical(self, "One-Shot Error", f"Failed to open One-Shot game creation: {str(e)}")
    
    def _open_surprise_game_creation(self):
        """Open Surprise AI game creation dialog"""
        try:
            # Check if API key is configured for AI functionality
            if not is_gamai_configured():
                QMessageBox.warning(
                    self, 
                    "API Key Required", 
                    "AI-powered game generation requires a Gemini API key. Please configure it first."
                )
                return
            
            dialog = SurpriseGameDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                # Game creation is handled within the dialog
                pass
        except Exception as e:
            QMessageBox.critical(self, "Surprise Error", f"Failed to open Surprise game creation: {str(e)}")
    
    def _open_foryou_game_creation(self):
        """Open For You AI game creation dialog"""
        try:
            # Check if API key is configured for AI functionality
            if not is_gamai_configured():
                QMessageBox.warning(
                    self, 
                    "API Key Required", 
                    "AI-powered game generation requires a Gemini API key. Please configure it first."
                )
                return
            
            # Check if there are any games to use as inspiration
            if not self.games:
                QMessageBox.information(
                    self,
                    "No Games Available",
                    "You need at least one game in your collection to use the 'For You' feature.\n\n"
                    "Please add some games first using the '+' button or other import methods."
                )
                return
            
            dialog = ForYouGameDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                # Game creation is handled within the dialog
                pass
        except Exception as e:
            QMessageBox.critical(self, "For You Error", f"Failed to open For You game creation: {str(e)}")
    
    def _create_new_game(self):
        """Create a new game"""
        dialog = GameCreationDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            game_data = dialog.game_data
            new_game = self.game_service.create_game(
                game_data["name"], 
                game_data["version"],
                game_type=game_data["type"],
                players=game_data["players"],
                main_categories=game_data["main_categories"],
                sub_categories=game_data["sub_categories"]
            )
            
            if new_game:
                # Open editor for the new game
                self._open_editor(new_game)
            else:
                QMessageBox.critical(self, "Error", "Failed to create new game.")
    
    def _edit_existing_game(self):
        """Edit an existing game"""
        games = self.game_service.discover_games()
        
        if not games:
            QMessageBox.information(self, "No Games", "No games found to edit.")
            return
        
        # Simple dialog to select game
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Game to Edit")
        dialog.setFixedSize(400, 500)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        
        # Title
        title_label = QLabel("Select a game to edit:")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: white; margin: 10px;")
        layout.addWidget(title_label)
        
        # Scroll area for games
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("QScrollArea { border: none; }")
        
        games_widget = QWidget()
        games_layout = QVBoxLayout(games_widget)
        games_layout.setSpacing(5)
        
        for game in games:
            button = QPushButton(f"{game.name} (v{game.version}) - Type: {game.type} | Players: {game.players}")
            button.setFixedHeight(40)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: white;
                    border: 1px solid #3a3a3a;
                    border-radius: 5px;
                    font-size: 12px;
                    text-align: left;
                    padding-left: 10px;
                }
                QPushButton:hover {
                    background-color: #3a3a3a;
                }
            """)
            button.clicked.connect(lambda checked, g=game: (dialog.close(), self._open_editor(g)))
            games_layout.addWidget(button)
        
        games_layout.addStretch()
        scroll_area.setWidget(games_widget)
        layout.addWidget(scroll_area)
        
        # Cancel button
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedHeight(30)
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #777;
            }
        """)
        cancel_button.clicked.connect(dialog.close)
        layout.addWidget(cancel_button)
        
        dialog.setStyleSheet("background-color: #1a1a1a;")
        dialog.exec_()
    
    def _import_game(self):
        """Import a game from external HTML file"""
        # Show file dialog to select HTML file
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select HTML Game File",
            "",
            "HTML Files (*.html *.htm);;All Files (*)"
        )
        
        if not file_path:
            return  # User cancelled
        
        try:
            # Read the selected HTML file
            with open(file_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            
            # Validate that it's HTML content
            if not html_content.strip().lower().startswith('<!doctype') and '<html' not in html_content.lower():
                QMessageBox.warning(
                    self, 
                    "Invalid File", 
                    "Selected file does not appear to be a valid HTML file."
                )
                return
            
            # Get file name without extension for potential game name
            source_file = Path(file_path)
            suggested_name = source_file.stem.replace('_', ' ').replace('-', ' ').title()
            
            # Show import metadata dialog
            dialog = GameImportDialog(self, suggested_name)
            if dialog.exec_() != QDialog.Accepted:
                return
            
            game_data = dialog.game_data
            
            # Create new game with imported content
            new_game = self.game_service.import_game(
                html_content,
                game_data["name"],
                game_data["version"],
                main_categories=game_data["main_categories"],
                sub_categories=game_data["sub_categories"]
            )
            
            if new_game:
                QMessageBox.information(
                    self, 
                    "Import Successful", 
                    f"Game '{game_data['name']}' imported successfully!"
                )
                # Load games and highlight the newly imported one
                # Stay in main menu instead of opening editor
                self._load_games_async(highlight_game_name=new_game.name)
            else:
                QMessageBox.critical(self, "Import Failed", "Failed to import the game.")
                
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import game: {str(e)}")
    
    def _export_game(self):
        """Export games to zip files"""
        try:
            dialog = ExportGameDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                selected_games = dialog.get_selected_games()
                if not selected_games:
                    QMessageBox.information(self, "No Selection", "Please select at least one game to export.")
                    return
                
                success_count = 0
                failed_games = []
                
                if len(selected_games) == 1:
                    # Single game: export individually
                    try:
                        if self._export_single_game(selected_games[0], selected_games):
                            success_count = 1
                        else:
                            failed_games.append(selected_games[0].name)
                    except Exception as e:
                        failed_games.append(f"{selected_games[0].name} ({str(e)})")
                else:
                    # Multi-game: export all in one zip file
                    try:
                        if self._export_multiple_games(selected_games):
                            success_count = len(selected_games)
                        else:
                            failed_games.extend([game.name for game in selected_games])
                    except Exception as e:
                        failed_games.append(f"Multi-export ({str(e)})")
                
                # Show results
                if success_count > 0:
                    if len(failed_games) > 0:
                        QMessageBox.information(
                            self,
                            "Export Results",
                            f"✅ Successfully exported {success_count} game(s).\n❌ Failed to export: {', '.join(failed_games)}"
                        )
                    else:
                        QMessageBox.information(
                            self,
                            "Export Successful",
                            f"Successfully exported {success_count} game(s)!"
                        )
                else:
                    QMessageBox.critical(
                        self,
                        "Export Failed",
                        f"Failed to export all selected games.\nErrors: {', '.join(failed_games)}"
                    )
                
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to open export dialog: {str(e)}")
    
    def _export_multiple_games(self, selected_games):
        """Export multiple games to a single zip file"""
        try:
            # Check/create exports folder
            exports_dir = Path("exports")
            exports_dir.mkdir(exist_ok=True)
            
            # Multi-game export: "2025-12-2-6-37-42_3.zip" (timestamp_count.zip)
            now = datetime.now()
            zip_filename = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}-{now.second}_{len(selected_games)}.zip"
            zip_path = exports_dir / zip_filename
            
            # Handle duplicate names
            counter = 1
            while zip_path.exists():
                base_name = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}-{now.second}_{len(selected_games)}"
                zip_filename = f"{base_name}({counter}).zip"
                zip_path = exports_dir / zip_filename
                counter += 1
            
            # Create single zip file with all games
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for game in selected_games:
                    game_dir = Path(game.folder_path)
                    game_folder_name = game_dir.name  # Get the folder name
                    
                    # Zip each game folder with its contents
                    for file_path in game_dir.rglob('*'):
                        if file_path.is_file():
                            # Create archive path that includes the game folder name
                            arcname = game_folder_name / file_path.relative_to(game_dir)
                            zipf.write(file_path, arcname)
            
            return True
            
        except Exception as e:
            print(f"Failed to export multiple games: {e}")
            return False

    def _export_single_game(self, game, selected_games):
        """Export a single game to zip file"""
        try:
            # Check/create exports folder
            exports_dir = Path("exports")
            exports_dir.mkdir(exist_ok=True)
            
            # Generate zip filename based on selection count
            if len(selected_games) == 1:
                # Single game export: "game_name_v1.1.1.zip"
                zip_filename = f"{game.name}_v{game.version}.zip"
            else:
                # Multi-game export: "2025-12-2-5-56-0_3.zip" (timestamp_count.zip)
                now = datetime.now()
                zip_filename = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}-{now.second}_{len(selected_games)}.zip"
            
            zip_path = exports_dir / zip_filename
            
            # Handle duplicate names
            counter = 1
            while zip_path.exists():
                if len(selected_games) == 1:
                    # Single game: use game name_version(X).zip
                    name_part = f"{game.name}_v{game.version}"
                    zip_filename = f"{name_part}({counter}).zip"
                else:
                    # Multi-game: just increment the timestamp file name
                    base_name = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}-{now.second}_{len(selected_games)}"
                    zip_filename = f"{base_name}({counter}).zip"
                zip_path = exports_dir / zip_filename
                counter += 1
            
            # Create zip file
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                game_dir = Path(game.folder_path)
                game_folder_name = game_dir.name  # Get the folder name
                
                # Zip the entire folder with its contents
                for file_path in game_dir.rglob('*'):
                    if file_path.is_file():
                        # Create archive path that includes the game folder name
                        arcname = game_folder_name / file_path.relative_to(game_dir)
                        zipf.write(file_path, arcname)
            
            return True
            
        except Exception as e:
            print(f"Failed to export game {game.name}: {e}")
            return False
    
    def _open_editor(self, game):
        """Open code editor for a game (integrated in main window)"""
        # Hide other views
        self.game_list.setVisible(False)
        self.game_player.setVisible(False)
        
        # Clean up existing editor widget if it exists
        if self.editor_widget is not None:
            # Stop the auto-refresh timer
            if hasattr(self.editor_widget, 'auto_refresh_timer') and self.editor_widget.auto_refresh_timer:
                self.editor_widget.auto_refresh_timer.stop()
                self.editor_widget.auto_refresh_timer = None
            
            # Clean up preview tracking attribute
            if hasattr(self.editor_widget, 'last_preview_content'):
                delattr(self.editor_widget, 'last_preview_content')
            
            # Remove and delete the old widget
            self.editor_layout.removeWidget(self.editor_widget)
            self.editor_widget.deleteLater()
            self.editor_widget = None
        
        # Create fresh editor widget
        self.editor_widget = EnhancedCodeEditorWidget(game, self.game_service, self)
        self.editor_widget.gameSaved.connect(self._on_game_saved)
        self.editor_widget.finishRequested.connect(self._on_editor_finished)
        self.editor_layout.addWidget(self.editor_widget)
        
        # Show editor view
        self.editor_view_container.setVisible(True)
        self._disable_top_bar_buttons()
        
        # Update AI context - user opened editor for game (same as _enter_edit_mode)
        GAMAI_CONTEXT.update_context_status("global", f"user opened editor for game '{game.name}'")
        GAMAI_CONTEXT.add_game_context("global", game.name, str(game.folder_path))
    
    def _on_game_saved(self, game):
        """Handle game save event"""
        # Refresh the game list to show updated games
        self._load_games_async()
    
    def _on_editor_finished(self):
        """Handle editor finish event - return to game list"""
        # Clean up editor widget
        if self.editor_widget is not None:
            # Stop the auto-refresh timer
            if hasattr(self.editor_widget, 'auto_refresh_timer') and self.editor_widget.auto_refresh_timer:
                self.editor_widget.auto_refresh_timer.stop()
                self.editor_widget.auto_refresh_timer = None
            
            # Clean up preview tracking attribute
            if hasattr(self.editor_widget, 'last_preview_content'):
                delattr(self.editor_widget, 'last_preview_content')
            
            # Remove and delete the widget
            self.editor_layout.removeWidget(self.editor_widget)
            self.editor_widget.deleteLater()
            self.editor_widget = None
        
        # Hide editor view
        self.editor_view_container.setVisible(False)
        
        # Show game list
        self.game_list.setVisible(True)
        
        # Update AI context - user returned to main menu from editor
        if self.game_player.current_game:
            GAMAI_CONTEXT.update_context_status("global", f"user returned to main menu from editing game '{self.game_player.current_game.name}'")
        else:
            GAMAI_CONTEXT.update_context_status("global", "user returned to main menu from editor")
        
        # Refresh the game list to show updated games
        self._load_games_async()
        self._enable_top_bar_buttons()
    
    def _load_games_async(self, highlight_game_name=None):
        """Load games in background thread to prevent UI freeze"""
        
        # Worker thread for game discovery
        class GameDiscoveryThread(QThread):
            discovery_finished = pyqtSignal(list)
            discovery_error = pyqtSignal(str)
            
            def __init__(self, service):
                super().__init__()
                self.service = service
                
            def run(self):
                try:
                    games = self.service.discover_games()
                    self.discovery_finished.emit(games)
                except Exception as e:
                    self.discovery_error.emit(str(e))

        self.discovery_thread = GameDiscoveryThread(self.game_service)
        self.discovery_thread.discovery_finished.connect(lambda games: self._on_games_loaded(games, highlight_game_name))
        self.discovery_thread.discovery_error.connect(self._show_error)
        self.discovery_thread.start()
        
    def _on_games_loaded(self, games, highlight_game_name=None):
        """Callback when games are loaded"""
        self.games = games
        self.game_list.display_games(self.games)
        
        # Reset search state when games are reloaded
        self.original_games = []
        self.current_filtered_games = []
        self.is_filtered = False
        self.show_all_button.setVisible(False)
        
        # Highlight specific game if provided
        if highlight_game_name:
            QTimer.singleShot(500, lambda: self.game_list.highlight_game(highlight_game_name))
    
    def _on_game_selected(self, game):
        """Handle game selection and show options dialog"""
        dialog = GameOptionsDialog(game, self)
        if dialog.exec_() == QDialog.Accepted:
            if dialog.choice == "play":
                # NEW: Increment played_times auto-tracking before launching
                game.played_times += 1
                game.save_manifest()
                # Launch the game
                if self.game_player.play_game(game):
                    # Update AI context - user is playing a game
                    GAMAI_CONTEXT.update_context_status("global", f"user started playing game '{game.name}'")
                    
                    self._disable_top_bar_buttons()
                    self.game_list.setVisible(False)
                    self.game_player.setVisible(True)
                else:
                    self._show_error(f"Failed to load game: {game.name}\nCheck if 'index.html' exists in the game folder.")
            elif dialog.choice == "edit":
                self._open_editor(game)
    
    def _return_to_list(self):
        """Return to game selection list"""
        self.game_player.stop_game()
        self.game_player.setVisible(False)
        self.game_list.setVisible(True)
        
        # Clear selection cache when exiting game
        clear_selection_cache()
        
        # Update AI context - user returned to main menu from game
        GAMAI_CONTEXT.update_context_status("global", "user returned to main menu from game")
        
        self._enable_top_bar_buttons()
    
    def _disable_top_bar_buttons(self):
        """Disable and gray out top bar buttons during game play or editor mode"""
        # Disable create button (green -> gray)
        self.create_button.setEnabled(False)
        self.create_button.setCursor(Qt.ArrowCursor)
        self.create_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
                border-radius: 8px;
                font-size: 24px;
                font-weight: bold;
                color: #666;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
            }
        """)
        
        # Disable search button (blue -> gray)
        self.search_button.setEnabled(False)
        self.search_button.setCursor(Qt.ArrowCursor)
        self.search_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
                color: #666;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
            }
        """)
        
        # Disable view toggle button (white -> gray)
        self.view_toggle_button.setEnabled(False)
        self.view_toggle_button.setCursor(Qt.ArrowCursor)
        self.view_toggle_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
                padding: 8px 15px;
                color: #666;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
            }
        """)
        
        # Disable AI button (purple -> gray)
        self.ai_button.setEnabled(False)
        self.ai_button.setCursor(Qt.ArrowCursor)
        self.ai_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
                border-radius: 8px;
                font-size: 20px;
                font-weight: bold;
                color: #666;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #555;
            }
        """)
    
    def _enable_top_bar_buttons(self):
        """Re-enable top bar buttons when returning to main menu"""
        # Restore create button (gray -> green)
        self.create_button.setEnabled(True)
        self.create_button.setCursor(Qt.PointingHandCursor)
        self.create_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 24px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        
        # Restore search button (gray -> blue)
        self.search_button.setEnabled(True)
        self.search_button.setCursor(Qt.PointingHandCursor)
        self.search_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
        """)
        
        # Restore view toggle button (gray -> white)
        self.view_toggle_button.setEnabled(True)
        self.view_toggle_button.setCursor(Qt.PointingHandCursor)
        self.view_toggle_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 18px;
                font-weight: bold;
                padding: 8px 15px;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
        """)
        
        # Restore AI button (gray -> purple)
        self.ai_button.setEnabled(True)
        self.ai_button.setCursor(Qt.PointingHandCursor)
        self.ai_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #121212, stop:0.7 #1a1a1a, stop:1 #121212);
                border: 2px solid #E5E5E5;
                border-radius: 8px;
                font-size: 20px;
                font-weight: bold;
                color: white;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #121212, stop:0.3 #161616, stop:0.7 #1e1e1e, stop:1 #121212);
                border: 2px solid #E5E5E5;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, 
                    stop:0 #0e0e0e, stop:0.3 #121212, stop:0.7 #161616, stop:1 #0e0e0e);
                border: 2px solid #E5E5E5;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                border: 2px solid #555;
                color: #666;
            }
            QPushButton:pressed {
                background-color: #E5E5E5;
            }
        """)
    
    def _show_error(self, message):
        """Show error dialog"""
        QMessageBox.critical(self, "GameBox Error", message)
    
    def toggle_fullscreen(self):
        """Toggle between fullscreen and windowed mode"""
        if self.is_fullscreen:
            self.showNormal()
            self.is_fullscreen = False
        else:
            self.showFullScreen()
            self.is_fullscreen = True
    
    def keyPressEvent(self, event):
        """Handle keyboard events (Escape to exit game/app, F11 to toggle fullscreen)"""
        if event.key() == Qt.Key_Escape:
            if self.game_player.isVisible():
                # If in game, return to list
                self._return_to_list()
            else:
                # If in list, close application
                self.close()
        elif event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            
    def add_activity_log(self, log_entry):
        """Add activity log entry to global GAMAI context for AI awareness"""
        try:
            # Add to global GAMAI context for AI awareness
            GAMAI_CONTEXT.add_message("global", "system", f"📝 Activity Log: {log_entry}")
            
            # Also store locally for potential UI display
            if not hasattr(self, 'activity_logs'):
                self.activity_logs = []
            self.activity_logs.append({
                'timestamp': datetime.now().isoformat(),
                'log_entry': log_entry
            })
            
            # Keep only recent 50 activity logs locally
            if len(self.activity_logs) > 50:
                self.activity_logs = self.activity_logs[-50:]
            
            print(f"📝 Activity Log Added: {log_entry}")
            
        except Exception as e:
            print(f"Error adding activity log: {e}")

    def keyPressEvent(self, event):
        """Handle keyboard events (Escape to exit game/app, F11 to toggle fullscreen)"""
        if event.key() == Qt.Key_Escape:
            if self.game_player.isVisible():
                # If in game, return to list
                self._return_to_list()
            else:
                # If in list, close application
                self.close()
        elif event.key() == Qt.Key_F11:
            self.toggle_fullscreen()
            
        # Pass other events to the base class
        super().keyPressEvent(event)


def main():
    """Application entry point"""
    # Check for PyQtWebEngine
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        print("Error: PyQtWebEngine is not installed.")
        print("Please install it using: pip3 install PyQtWebEngine")
        sys.exit(1)
        
    app = QApplication(sys.argv)
    app.setApplicationName("GameBox")
    app.setApplicationDisplayName("GameBox")
    
    # Set application icon with multiple fallbacks and enhanced support
    def setup_application_icon():
        """Set application icon with comprehensive support"""
        # Use resource_path for PyInstaller onefile mode compatibility
        icon_paths = [
            resource_path("logo.png"),
            resource_path("GameBox7.ico"),
            resource_path("GameBox7.png"),
            "logo.png", "GameBox7.ico", "GameBox7.png"  # Fallback for dev mode
        ]
        icon = None
        
        # Try to load icon with multiple fallbacks
        for path in icon_paths:
            try:
                if Path(path).exists():
                    icon = QIcon(path)
                    print(f"✅ Found icon at: {path}")
                    break
            except Exception as e:
                print(f"⚠️ Failed to load icon from {path}: {e}")
                continue
        
        if icon is None:
            # Create a default icon from logo.png if it exists
            try:
                logo_path = resource_path("logo.png")
                if Path(logo_path).exists():
                    pixmap = QPixmap(logo_path)
                    # Resize to standard taskbar icon sizes
                    icon = QIcon(pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    print("✅ Created scaled icon from logo.png")
                elif Path("logo.png").exists():
                    # Fallback for dev mode
                    pixmap = QPixmap("logo.png")
                    icon = QIcon(pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                    print("✅ Created scaled icon from logo.png (dev mode)")
                else:
                    print("⚠️ No logo.png found for icon creation")
                    return
            except Exception as e:
                print(f"⚠️ Could not create icon from logo.png: {e}")
                return
        
        # Set icon at application level (taskbar, task manager, etc.)
        app.setWindowIcon(icon)  # This is the correct method for PyQt5
        
        # Platform-specific enhancements
        try:
            # Set high DPI scaling for better icon quality
            app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
            print("✅ High DPI pixmaps enabled for better icon quality")
        except:
            pass
        
        # Verify icon was set
        if not app.windowIcon().isNull():
            print("✅ Application icon verified - should appear in taskbar and system")
        else:
            print("⚠️ Application icon verification failed")
        
        print("✅ Application icon set successfully for taskbar and window decorations")
    
    # Set up the application icon
    setup_application_icon()
    
    # Initialize GAMAI configuration
    ensure_gamai_config()
    
    window = GameBox()
    window.show()
    
    # Ensure icon appears after window is shown
    QTimer.singleShot(200, lambda: app.setWindowIcon(app.windowIcon()))
    
    # Set organization name for better identification
    app.setOrganizationName("GameBox")
    
    # Start the application event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()