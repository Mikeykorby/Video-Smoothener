#!/usr/bin/env python3
"""
Video Enhancer Pro - Universal Video Enhancement Suite
A beautiful, modern GUI application for video frame interpolation and upscaling.

Features:
- Beautiful Modern UI with dark theme
- Frame Interpolation: Increase frame rate using motion compensation
- GPU Acceleration: NVIDIA (NVENC), AMD (AMF/VCE), Intel (QSV), and CPU
- Upscaling: Increase video resolution with lanczos/spline36
- Batch Processing: Queue multiple videos
- Real-time Progress: Live encoding progress with ETA
- Drag & Drop: Easy file loading
- Cross-platform: Windows, macOS, Linux

Repository: https://github.com/Mikeykorby/Video-Smoothener.git
"""

import argparse
import subprocess
import sys
import os
import shutil
import json
import re
import threading
import time
import platform
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Callable
from dataclasses import dataclass, asdict
from queue import Queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


@dataclass
class GPUConfig:
    """GPU configuration for different vendors"""
    name: str
    encoder: str
    decoder: Optional[str]
    scale_filter: str
    hwaccel: Optional[str]
    supported: bool = True

    def to_dict(self):
        return asdict(self)


@dataclass
class VideoTask:
    """Represents a video processing task"""
    input_path: str
    output_path: str
    target_fps: int
    upscale: Optional[str]
    preset: str
    gpu_type: str
    status: str = "pending"  # pending, processing, completed, failed
    progress: float = 0.0
    eta: str = "--:--"
    error_msg: str = ""


class GPUManager:
    """Cross-platform GPU detection and configuration"""

    GPU_CONFIGS = {
        "nvidia": GPUConfig(
            name="NVIDIA",
            encoder="h264_nvenc",
            decoder="h264_cuvid",
            scale_filter="scale={width}:{height}:flags={scale_flags}:format=yuv420p",
            hwaccel="cuda",
            supported=True
        ),
        "amd": GPUConfig(
            name="AMD",
            encoder="h264_amf",
            decoder=None,
            scale_filter="scale={width}:{height}:flags={scale_flags}:format=yuv420p",
            hwaccel=None,
            supported=True
        ),
        "intel": GPUConfig(
            name="Intel",
            encoder="h264_qsv",
            decoder="h264_qsv",
            scale_filter="scale={width}:{height}:flags={scale_flags}:format=yuv420p",
            hwaccel="qsv",
            supported=True
        ),
        "cpu": GPUConfig(
            name="CPU",
            encoder="libx264",
            decoder=None,
            scale_filter="scale={width}:{height}:flags={scale_flags}:format=yuv420p",
            hwaccel=None,
            supported=True
        ),
        "apple": GPUConfig(
            name="Apple Silicon",
            encoder="h264_videotoolbox",
            decoder="h264",
            scale_filter="scale={width}:{height}:flags={scale_flags}:format=yuv420p",
            hwaccel="videotoolbox",
            supported=True
        )
    }

    @classmethod
    def detect_gpu(cls) -> str:
        """Auto-detect GPU type across platforms"""
        system = platform.system()

        # Check for NVIDIA
        try:
            result = subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return "nvidia"
        except:
            pass

        # Check for Apple Silicon
        if system == "Darwin":
            try:
                result = subprocess.run(
                    ["system_profiler", "SPDisplaysDataType"],
                    capture_output=True, text=True, timeout=5
                )
                if "Apple" in result.stdout:
                    return "apple"
            except:
                pass

        # Check for Intel QSV
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", 
                 "-init_hw_device", "qsv", "-f", "lavfi", "-i", "nullsrc", 
                 "-frames:v", "0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return "intel"
        except:
            pass

        # Check for AMD on Linux
        if system == "Linux":
            try:
                if os.path.exists("/sys/class/drm"):
                    for entry in os.listdir("/sys/class/drm"):
                        vendor_path = f"/sys/class/drm/{entry}/device/vendor"
                        if os.path.exists(vendor_path):
                            with open(vendor_path, 'r') as f:
                                vendor = f.read().strip()
                                if vendor == "0x1002":  # AMD vendor ID
                                    return "amd"
            except:
                pass

        # Check for AMD on Windows
        if system == "Windows":
            try:
                result = subprocess.run(
                    ["wmic", "path", "win32_VideoController", "get", "Name"],
                    capture_output=True, text=True, timeout=10
                )
                output = result.stdout.upper()
                if any(x in output for x in ["AMD", "RADEON", "RX"]):
                    return "amd"
            except:
                pass

        return "cpu"

    @classmethod
    def get_config(cls, gpu_type: str) -> GPUConfig:
        """Get GPU configuration"""
        if gpu_type == "auto":
            gpu_type = cls.detect_gpu()
        return cls.GPU_CONFIGS.get(gpu_type, cls.GPU_CONFIGS["cpu"])


class FFmpegManager:
    """Manages FFmpeg discovery and execution"""

    PRESETS = {
        "fast": {
            "description": "Fast processing - lower quality but quick",
            "crf": "23",
            "preset": "fast",
            "minterpolate_mode": "mci",
            "minterpolate_search": "bidir",
            "minterpolate_complexity": "low",
            "scale_flags": "fast_bilinear",
            "gpu_quality": "speed",
        },
        "balanced": {
            "description": "Balanced - good quality at reasonable speed",
            "crf": "18",
            "preset": "medium",
            "minterpolate_mode": "mci",
            "minterpolate_search": "bidir",
            "minterpolate_complexity": "medium",
            "scale_flags": "lanczos",
            "gpu_quality": "quality",
        },
        "quality": {
            "description": "High quality - best results but slower",
            "crf": "14",
            "preset": "slow",
            "minterpolate_mode": "mci",
            "minterpolate_search": "bidir",
            "minterpolate_complexity": "high",
            "scale_flags": "spline36",
            "gpu_quality": "quality",
        }
    }

    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()
        self.ffprobe_path = self._find_ffprobe()

    def _find_ffmpeg(self) -> str:
        """Find FFmpeg executable across platforms"""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg

        # Platform-specific common locations
        system = platform.system()
        common_paths = []

        if system == "Windows":
            common_paths = [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
                os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
            ]
        elif system == "Darwin":  # macOS
            common_paths = [
                "/usr/local/bin/ffmpeg",
                "/opt/homebrew/bin/ffmpeg",
                "/opt/local/bin/ffmpeg",
            ]
        else:  # Linux
            common_paths = [
                "/usr/bin/ffmpeg",
                "/usr/local/bin/ffmpeg",
                "/snap/bin/ffmpeg",
            ]

        for path in common_paths:
            if os.path.isfile(path):
                return path

        raise RuntimeError(
            "FFmpeg not found! Please install FFmpeg and add it to PATH.\n"
            "Download from: https://ffmpeg.org/download.html"
        )

    def _find_ffprobe(self) -> str:
        """Find FFprobe executable"""
        ffprobe = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
        if os.path.exists(ffprobe):
            return ffprobe

        ffprobe_alt = shutil.which("ffprobe")
        if ffprobe_alt:
            return ffprobe_alt

        raise RuntimeError("FFprobe not found! It should be installed with FFmpeg.")

    def get_video_info(self, input_path: str) -> dict:
        """Get video information using ffprobe"""
        cmd = [
            self.ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except:
            return {}

    def get_video_dimensions(self, input_path: str) -> Tuple[int, int]:
        """Get video width and height"""
        info = self.get_video_info(input_path)
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                return stream.get("width", 1920), stream.get("height", 1080)
        return 1920, 1080

    def get_video_duration(self, input_path: str) -> float:
        """Get video duration in seconds"""
        info = self.get_video_info(input_path)

        # Try format duration first
        duration = info.get("format", {}).get("duration")
        if duration:
            try:
                return float(duration)
            except:
                pass

        # Try stream duration
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                duration = stream.get("duration")
                if duration:
                    try:
                        return float(duration)
                    except:
                        pass

                # Calculate from frame rate and frame count
                nb_frames = stream.get("nb_frames")
                fps_str = stream.get("r_frame_rate", "30/1")
                if nb_frames and fps_str:
                    try:
                        num, den = map(int, fps_str.split("/"))
                        fps = num / den if den != 0 else 30
                        return int(nb_frames) / fps
                    except:
                        pass

        return 0.0

    def get_frame_count(self, input_path: str) -> int:
        """Get total frame count"""
        info = self.get_video_info(input_path)
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                nb_frames = stream.get("nb_frames")
                if nb_frames:
                    try:
                        return int(nb_frames)
                    except:
                        pass
        return 0

    def generate_thumbnail(self, input_path: str, output_path: str, time_offset: str = "00:00:01") -> bool:
        """Generate thumbnail from video"""
        cmd = [
            self.ffmpeg_path,
            "-ss", time_offset,
            "-i", input_path,
            "-vframes", "1",
            "-q:v", "2",
            "-y",
            output_path
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=30)
            return os.path.exists(output_path)
        except:
            return False

    def parse_upscale(self, upscale_str: str, orig_w: int = 1920, orig_h: int = 1080) -> Tuple[int, int]:
        """Parse upscale parameter"""
        upscale_lower = upscale_str.lower().strip()

        presets = {
            "720p": (1280, 720),
            "1080p": (1920, 1080),
            "1440p": (2560, 1440),
            "2k": (2560, 1440),
            "4k": (3840, 2160),
            "2160p": (3840, 2160),
            "8k": (7680, 4320),
        }

        if upscale_lower in presets:
            return presets[upscale_lower]

        if upscale_lower.endswith("x"):
            try:
                multiplier = float(upscale_lower[:-1])
                return (int(orig_w * multiplier), int(orig_h * multiplier))
            except:
                pass

        if "x" in upscale_str:
            try:
                parts = upscale_str.split("x")
                return (int(parts[0]), int(parts[1]))
            except:
                pass

        raise ValueError(f"Invalid upscale format: {upscale_str}")

    def build_command(self, task: VideoTask, gpu_config: GPUConfig) -> List[str]:
        """Build FFmpeg command for a task"""
        preset = self.PRESETS.get(task.preset, self.PRESETS["balanced"])

        cmd = [self.ffmpeg_path]

        # Hardware acceleration initialization
        if gpu_config.hwaccel:
            cmd.extend(["-hwaccel", gpu_config.hwaccel])
            if gpu_config.hwaccel == "cuda":
                cmd.extend(["-hwaccel_output_format", "cuda"])

        # Input
        cmd.extend(["-i", task.input_path])

        # Build video filter
        filters = []

        # Motion interpolation
        complexity = preset["minterpolate_complexity"]
        if complexity == "low":
            mi_filter = f"minterpolate='fps={task.target_fps}:mi_mode=mci:mc_mode=fast_bilinear:me_mode=bidir'"
        elif complexity == "medium":
            mi_filter = f"minterpolate='fps={task.target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir'"
        else:
            mi_filter = f"minterpolate='fps={task.target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=epzs'"

        filters.append(mi_filter)

        # Upscaling
        if task.upscale:
            orig_w, orig_h = self.get_video_dimensions(task.input_path)
            final_w, final_h = self.parse_upscale(task.upscale, orig_w, orig_h)

            scale_flags = preset["scale_flags"]
            scale_filter = f"scale={final_w}:{final_h}:flags={scale_flags}:format=yuv420p"
            filters.append(scale_filter)

            # Sharpening for quality preset
            if task.preset == "quality":
                filters.append("unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=1.0")

        # Apply filters
        vf = ",".join(filters)
        cmd.extend(["-vf", vf])

        # Video encoder
        cmd.extend(["-c:v", gpu_config.encoder])

        # Encoder-specific settings
        if gpu_config.name == "NVIDIA":
            cmd.extend(["-preset", preset["preset"], "-cq", preset["crf"]])
        elif gpu_config.name == "AMD":
            quality = "quality" if task.preset == "quality" else "speed" if task.preset == "fast" else "balanced"
            cmd.extend(["-quality", quality, "-rc", "cqp", "-qp_p", preset["crf"], "-qp_i", preset["crf"]])
        elif gpu_config.name == "Intel":
            cmd.extend(["-preset", preset["preset"], "-global_quality", preset["crf"]])
        elif gpu_config.name == "Apple Silicon":
            cmd.extend(["-q:v", preset["crf"]])
        else:
            cmd.extend(["-preset", preset["preset"], "-crf", preset["crf"]])

        # Force target FPS
        cmd.extend(["-r", str(task.target_fps)])

        # Audio
        cmd.extend(["-c:a", "aac", "-b:a", "320k"])

        # Pixel format
        cmd.extend(["-pix_fmt", "yuv420p"])

        # Progress output
        cmd.extend(["-progress", "pipe:1", "-nostats"])

        # Output
        cmd.extend(["-y", task.output_path])

        return cmd

    def run_with_progress(self, task: VideoTask, gpu_config: GPUConfig, 
                         progress_callback: Callable[[float, str], None],
                         log_callback: Callable[[str], None]) -> bool:
        """Run FFmpeg with progress tracking"""

        duration = self.get_video_duration(task.input_path)
        total_frames = self.get_frame_count(task.input_path)

        # If no frame count, estimate from duration
        if total_frames == 0 and duration > 0:
            # Estimate based on target fps (output will have more frames)
            total_frames = int(duration * task.target_fps)

        cmd = self.build_command(task, gpu_config)

        log_callback(f"Command: {' '.join(cmd)}\n")

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            current_frame = 0
            current_time = 0.0

            for line in process.stdout:
                line = line.strip()
                log_callback(line + "\n")

                # Parse progress
                if line.startswith("frame="):
                    try:
                        frame_match = re.search(r'frame=\s*(\d+)', line)
                        if frame_match:
                            current_frame = int(frame_match.group(1))

                        time_match = re.search(r'time=(\d+):\d+:\d+', line)
                        if time_match:
                            current_time = float(time_match.group(1)) * 3600

                        if total_frames > 0:
                            progress = min(100.0, (current_frame / total_frames) * 100)

                            # Calculate ETA
                            if current_time > 0 and duration > 0:
                                remaining = duration - current_time
                                eta_mins = int(remaining / 60)
                                eta_secs = int(remaining % 60)
                                eta_str = f"{eta_mins:02d}:{eta_secs:02d}"
                            else:
                                eta_str = "calculating..."

                            progress_callback(progress, eta_str)
                    except:
                        pass

            process.wait()

            if process.returncode == 0:
                progress_callback(100.0, "00:00")
                return True
            else:
                log_callback(f"\nFFmpeg exited with code {process.returncode}\n")
                return False

        except Exception as e:
            log_callback(f"\nError: {str(e)}\n")
            return False


class SettingsManager:
    """Manages application settings persistence"""

    def __init__(self):
        self.config_dir = Path.home() / ".video_enhancer_pro"
        self.config_file = self.config_dir / "settings.json"
        self.config_dir.mkdir(exist_ok=True)

        self.defaults = {
            "last_input_dir": str(Path.home()),
            "last_output_dir": str(Path.home()),
            "default_preset": "balanced",
            "default_gpu": "auto",
            "default_fps": 60,
            "window_geometry": "1200x800+100+100",
            "theme": "dark"
        }

        self.settings = self.load()

    def load(self) -> dict:
        """Load settings from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults
                    return {**self.defaults, **loaded}
            except:
                pass
        return self.defaults.copy()

    def save(self):
        """Save settings to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except:
            pass

    def get(self, key: str, default=None):
        return self.settings.get(key, default)

    def set(self, key: str, value):
        self.settings[key] = value
        self.save()


class ModernTheme:
    """Modern dark theme for tkinter"""

    COLORS = {
        "bg_primary": "#0f0f0f",
        "bg_secondary": "#1a1a1a",
        "bg_tertiary": "#252525",
        "bg_card": "#1e1e1e",
        "accent": "#00d4aa",
        "accent_hover": "#00b894",
        "accent_secondary": "#3498db",
        "text_primary": "#ffffff",
        "text_secondary": "#b0b0b0",
        "text_muted": "#6c757d",
        "border": "#2d2d2d",
        "success": "#00d4aa",
        "warning": "#f39c12",
        "error": "#e74c3c",
        "info": "#3498db",
    }

    @classmethod
    def apply(cls, root: tk.Tk):
        """Apply modern theme to tkinter application"""
        style = ttk.Style()
        style.theme_use('clam')

        # Configure colors
        style.configure("Modern.TFrame", background=cls.COLORS["bg_primary"])
        style.configure("Card.TFrame", background=cls.COLORS["bg_card"])

        style.configure("Modern.TLabel", 
                       background=cls.COLORS["bg_primary"],
                       foreground=cls.COLORS["text_primary"],
                       font=("Segoe UI", 10))

        style.configure("Title.TLabel",
                       background=cls.COLORS["bg_primary"],
                       foreground=cls.COLORS["text_primary"],
                       font=("Segoe UI", 24, "bold"))

        style.configure("Subtitle.TLabel",
                       background=cls.COLORS["bg_primary"],
                       foreground=cls.COLORS["text_secondary"],
                       font=("Segoe UI", 11))

        style.configure("Modern.TButton",
                       background=cls.COLORS["accent"],
                       foreground=cls.COLORS["bg_primary"],
                       font=("Segoe UI", 10, "bold"),
                       padding=(20, 10))

        style.map("Modern.TButton",
                 background=[("active", cls.COLORS["accent_hover"]), ("pressed", cls.COLORS["accent"])])

        style.configure("Secondary.TButton",
                       background=cls.COLORS["bg_tertiary"],
                       foreground=cls.COLORS["text_primary"],
                       font=("Segoe UI", 10),
                       padding=(15, 8))

        style.configure("Modern.TCombobox",
                       fieldbackground=cls.COLORS["bg_tertiary"],
                       background=cls.COLORS["bg_tertiary"],
                       foreground=cls.COLORS["text_primary"],
                       arrowcolor=cls.COLORS["text_primary"])

        style.configure("Modern.TEntry",
                       fieldbackground=cls.COLORS["bg_tertiary"],
                       foreground=cls.COLORS["text_primary"],
                       insertcolor=cls.COLORS["text_primary"])

        style.configure("Modern.TCheckbutton",
                       background=cls.COLORS["bg_primary"],
                       foreground=cls.COLORS["text_primary"])

        style.configure("Modern.Horizontal.TProgressbar",
                       background=cls.COLORS["accent"],
                       troughcolor=cls.COLORS["bg_tertiary"],
                       bordercolor=cls.COLORS["bg_primary"],
                       lightcolor=cls.COLORS["accent"],
                       darkcolor=cls.COLORS["accent"])

        # Treeview styling
        style.configure("Modern.Treeview",
                       background=cls.COLORS["bg_card"],
                       foreground=cls.COLORS["text_primary"],
                       fieldbackground=cls.COLORS["bg_card"],
                       rowheight=30)

        style.configure("Modern.Treeview.Heading",
                       background=cls.COLORS["bg_tertiary"],
                       foreground=cls.COLORS["text_primary"],
                       font=("Segoe UI", 10, "bold"))

        style.map("Modern.Treeview",
                 background=[("selected", cls.COLORS["accent"])],
                 foreground=[("selected", cls.COLORS["bg_primary"])])

        # Notebook styling
        style.configure("Modern.TNotebook",
                       background=cls.COLORS["bg_primary"],
                       tabmargins=(2, 5, 2, 0))

        style.configure("Modern.TNotebook.Tab",
                       background=cls.COLORS["bg_tertiary"],
                       foreground=cls.COLORS["text_secondary"],
                       font=("Segoe UI", 10),
                       padding=(15, 8))

        style.map("Modern.TNotebook.Tab",
                 background=[("selected", cls.COLORS["accent"])],
                 foreground=[("selected", cls.COLORS["bg_primary"])],
                 expand=[("selected", [1, 1, 1, 0])])

        # Root configuration
        root.configure(background=cls.COLORS["bg_primary"])


class VideoEnhancerGUI:
    """Main GUI application"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Video Enhancer Pro")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)

        # Initialize managers
        self.settings = SettingsManager()
        self.ffmpeg = FFmpegManager()
        self.gpu_manager = GPUManager()

        # Task queue
        self.task_queue: Queue = Queue()
        self.tasks: List[VideoTask] = []
        self.current_task: Optional[VideoTask] = None
        self.processing = False
        self.process_thread: Optional[threading.Thread] = None

        # Apply theme
        ModernTheme.apply(root)

        # Build UI
        self._build_ui()

        # Load settings
        self._load_settings()

        # Detect GPU
        self._detect_gpu()

    def _build_ui(self):
        """Build the user interface"""
        # Main container with padding
        self.main_container = ttk.Frame(self.root, style="Modern.TFrame")
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Header
        self._build_header()

        # Content area (left: controls, right: queue + log)
        self.content = ttk.Frame(self.main_container, style="Modern.TFrame")
        self.content.pack(fill=tk.BOTH, expand=True, pady=(20, 0))
        self.content.columnconfigure(0, weight=1)
        self.content.columnconfigure(1, weight=2)
        self.content.rowconfigure(0, weight=1)

        # Left panel - Controls
        self._build_control_panel()

        # Right panel - Queue and Log
        self._build_right_panel()

        # Status bar
        self._build_status_bar()

    def _build_header(self):
        """Build header section"""
        header = ttk.Frame(self.main_container, style="Modern.TFrame")
        header.pack(fill=tk.X)

        # Logo/Title
        title_frame = ttk.Frame(header, style="Modern.TFrame")
        title_frame.pack(side=tk.LEFT)

        ttk.Label(title_frame, text="Video Enhancer", 
                 style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(title_frame, text="Professional frame interpolation & upscaling", 
                 style="Subtitle.TLabel").pack(anchor=tk.W)

        # GPU Badge
        self.gpu_badge = tk.Label(header, text="Detecting GPU...", 
                                  font=("Segoe UI", 9, "bold"),
                                  bg=ModernTheme.COLORS["bg_tertiary"],
                                  fg=ModernTheme.COLORS["accent"],
                                  padx=15, pady=5,
                                  relief=tk.FLAT,
                                  borderwidth=0)
        self.gpu_badge.pack(side=tk.RIGHT, padx=(0, 10))

    def _build_control_panel(self):
        """Build left control panel"""
        left_frame = ttk.Frame(self.content, style="Card.TFrame")
        left_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left_frame.columnconfigure(0, weight=1)

        # File Selection Section
        self._build_file_section(left_frame)

        # Settings Section
        self._build_settings_section(left_frame)

        # Action Buttons
        self._build_action_buttons(left_frame)

    def _build_file_section(self, parent):
        """Build file selection section"""
        section = ttk.Frame(parent, style="Card.TFrame")
        section.pack(fill=tk.X, padx=15, pady=15)
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="Source Video", 
                 font=("Segoe UI", 12, "bold"),
                 style="Modern.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        # Input file
        ttk.Label(section, text="Input:", style="Modern.TLabel").grid(row=1, column=0, sticky=tk.W, pady=5)

        input_frame = ttk.Frame(section, style="Card.TFrame")
        input_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0))
        input_frame.columnconfigure(0, weight=1)

        self.input_var = tk.StringVar()
        input_entry = tk.Entry(input_frame, textvariable=self.input_var,
                              bg=ModernTheme.COLORS["bg_tertiary"],
                              fg=ModernTheme.COLORS["text_primary"],
                              insertbackground=ModernTheme.COLORS["text_primary"],
                              relief=tk.FLAT, font=("Segoe UI", 10))
        input_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5), ipady=5)

        browse_btn = tk.Button(input_frame, text="Browse", command=self._browse_input,
                              bg=ModernTheme.COLORS["bg_tertiary"],
                              fg=ModernTheme.COLORS["text_primary"],
                              activebackground=ModernTheme.COLORS["accent"],
                              activeforeground=ModernTheme.COLORS["bg_primary"],
                              relief=tk.FLAT, font=("Segoe UI", 9),
                              padx=15, pady=3, cursor="hand2")
        browse_btn.grid(row=0, column=1)

        # Output file
        ttk.Label(section, text="Output:", style="Modern.TLabel").grid(row=2, column=0, sticky=tk.W, pady=5)

        output_frame = ttk.Frame(section, style="Card.TFrame")
        output_frame.grid(row=2, column=1, sticky="ew", padx=(10, 0))
        output_frame.columnconfigure(0, weight=1)

        self.output_var = tk.StringVar()
        output_entry = tk.Entry(output_frame, textvariable=self.output_var,
                               bg=ModernTheme.COLORS["bg_tertiary"],
                               fg=ModernTheme.COLORS["text_primary"],
                               insertbackground=ModernTheme.COLORS["text_primary"],
                               relief=tk.FLAT, font=("Segoe UI", 10))
        output_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5), ipady=5)

        out_browse_btn = tk.Button(output_frame, text="Browse", command=self._browse_output,
                                  bg=ModernTheme.COLORS["bg_tertiary"],
                                  fg=ModernTheme.COLORS["text_primary"],
                                  activebackground=ModernTheme.COLORS["accent"],
                                  activeforeground=ModernTheme.COLORS["bg_primary"],
                                  relief=tk.FLAT, font=("Segoe UI", 9),
                                  padx=15, pady=3, cursor="hand2")
        out_browse_btn.grid(row=0, column=1)

        # Video info display
        self.video_info_label = tk.Label(section, text="No video selected",
                                        font=("Segoe UI", 9),
                                        bg=ModernTheme.COLORS["bg_card"],
                                        fg=ModernTheme.COLORS["text_muted"])
        self.video_info_label.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))

    def _build_settings_section(self, parent):
        """Build settings section"""
        section = ttk.Frame(parent, style="Card.TFrame")
        section.pack(fill=tk.X, padx=15, pady=(0, 15))
        section.columnconfigure(1, weight=1)

        ttk.Label(section, text="Enhancement Settings", 
                 font=("Segoe UI", 12, "bold"),
                 style="Modern.TLabel").grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 15))

        # Target FPS
        ttk.Label(section, text="Target FPS:", style="Modern.TLabel").grid(row=1, column=0, sticky=tk.W, pady=5)

        fps_frame = ttk.Frame(section, style="Card.TFrame")
        fps_frame.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        self.fps_var = tk.IntVar(value=60)
        fps_values = [30, 60, 120, 144, 240]
        for i, fps in enumerate(fps_values):
            btn = tk.Radiobutton(fps_frame, text=str(fps), variable=self.fps_var, value=fps,
                                bg=ModernTheme.COLORS["bg_card"],
                                fg=ModernTheme.COLORS["text_secondary"],
                                selectcolor=ModernTheme.COLORS["accent"],
                                activebackground=ModernTheme.COLORS["bg_card"],
                                activeforeground=ModernTheme.COLORS["accent"],
                                font=("Segoe UI", 9))
            btn.pack(side=tk.LEFT, padx=(0, 10))

        # Preset
        ttk.Label(section, text="Quality:", style="Modern.TLabel").grid(row=2, column=0, sticky=tk.W, pady=10)

        self.preset_var = tk.StringVar(value="balanced")
        preset_combo = ttk.Combobox(section, textvariable=self.preset_var,
                                   values=["fast", "balanced", "quality"],
                                   state="readonly", width=20)
        preset_combo.grid(row=2, column=1, sticky="w", padx=(10, 0))

        # GPU Selection
        ttk.Label(section, text="GPU:", style="Modern.TLabel").grid(row=3, column=0, sticky=tk.W, pady=10)

        self.gpu_var = tk.StringVar(value="auto")
        gpu_combo = ttk.Combobox(section, textvariable=self.gpu_var,
                                values=["auto", "nvidia", "amd", "intel", "cpu", "apple"],
                                state="readonly", width=20)
        gpu_combo.grid(row=3, column=1, sticky="w", padx=(10, 0))

        # Upscale
        ttk.Label(section, text="Upscale:", style="Modern.TLabel").grid(row=4, column=0, sticky=tk.W, pady=10)

        self.upscale_var = tk.StringVar()
        upscale_combo = ttk.Combobox(section, textvariable=self.upscale_var,
                                    values=["", "2x", "4x", "720p", "1080p", "1440p", "4K", "8K"],
                                    state="normal", width=20)
        upscale_combo.grid(row=4, column=1, sticky="w", padx=(10, 0))
        ttk.Label(section, text="Leave empty for no upscaling", 
                 style="Modern.TLabel",
                 font=("Segoe UI", 8)).grid(row=5, column=1, sticky=tk.W, padx=(10, 0))

    def _build_action_buttons(self, parent):
        """Build action buttons"""
        btn_frame = ttk.Frame(parent, style="Card.TFrame")
        btn_frame.pack(fill=tk.X, padx=15, pady=(0, 15))

        self.add_btn = tk.Button(btn_frame, text="+ Add to Queue", command=self._add_to_queue,
                                bg=ModernTheme.COLORS["accent"],
                                fg=ModernTheme.COLORS["bg_primary"],
                                activebackground=ModernTheme.COLORS["accent_hover"],
                                activeforeground=ModernTheme.COLORS["bg_primary"],
                                relief=tk.FLAT, font=("Segoe UI", 11, "bold"),
                                padx=30, pady=12, cursor="hand2")
        self.add_btn.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = tk.Button(btn_frame, text="▶ Start Processing", command=self._start_processing,
                                  bg=ModernTheme.COLORS["bg_tertiary"],
                                  fg=ModernTheme.COLORS["text_primary"],
                                  activebackground=ModernTheme.COLORS["accent"],
                                  activeforeground=ModernTheme.COLORS["bg_primary"],
                                  relief=tk.FLAT, font=("Segoe UI", 11, "bold"),
                                  padx=30, pady=12, cursor="hand2")
        self.start_btn.pack(fill=tk.X, pady=(0, 10))

        self.stop_btn = tk.Button(btn_frame, text="⏹ Stop", command=self._stop_processing,
                                 bg=ModernTheme.COLORS["bg_tertiary"],
                                 fg=ModernTheme.COLORS["error"],
                                 activebackground=ModernTheme.COLORS["error"],
                                 activeforeground=ModernTheme.COLORS["text_primary"],
                                 relief=tk.FLAT, font=("Segoe UI", 11, "bold"),
                                 padx=30, pady=12, cursor="hand2",
                                 state=tk.DISABLED)
        self.stop_btn.pack(fill=tk.X)

    def _build_right_panel(self):
        """Build right panel with queue and log"""
        right_frame = ttk.Frame(self.content, style="Modern.TFrame")
        right_frame.grid(row=0, column=1, sticky="nsew")
        right_frame.rowconfigure(1, weight=2)
        right_frame.rowconfigure(3, weight=1)
        right_frame.columnconfigure(0, weight=1)

        # Queue Section
        ttk.Label(right_frame, text="Processing Queue", 
                 font=("Segoe UI", 14, "bold"),
                 style="Modern.TLabel").grid(row=0, column=0, sticky=tk.W, pady=(0, 10))

        # Queue Treeview
        queue_frame = ttk.Frame(right_frame, style="Card.TFrame")
        queue_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 15))
        queue_frame.rowconfigure(0, weight=1)
        queue_frame.columnconfigure(0, weight=1)

        columns = ("file", "fps", "upscale", "preset", "status", "progress")
        self.queue_tree = ttk.Treeview(queue_frame, columns=columns, show="headings",
                                      style="Modern.Treeview", height=8)

        self.queue_tree.heading("file", text="File")
        self.queue_tree.heading("fps", text="FPS")
        self.queue_tree.heading("upscale", text="Upscale")
        self.queue_tree.heading("preset", text="Preset")
        self.queue_tree.heading("status", text="Status")
        self.queue_tree.heading("progress", text="Progress")

        self.queue_tree.column("file", width=200)
        self.queue_tree.column("fps", width=60)
        self.queue_tree.column("upscale", width=80)
        self.queue_tree.column("preset", width=80)
        self.queue_tree.column("status", width=100)
        self.queue_tree.column("progress", width=100)

        scrollbar = ttk.Scrollbar(queue_frame, orient=tk.VERTICAL, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scrollbar.set)

        self.queue_tree.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=10)

        # Queue buttons
        queue_btn_frame = ttk.Frame(right_frame, style="Modern.TFrame")
        queue_btn_frame.grid(row=2, column=0, sticky=tk.W, pady=(0, 15))

        tk.Button(queue_btn_frame, text="Remove Selected", command=self._remove_selected,
                 bg=ModernTheme.COLORS["bg_tertiary"],
                 fg=ModernTheme.COLORS["text_primary"],
                 activebackground=ModernTheme.COLORS["error"],
                 activeforeground=ModernTheme.COLORS["text_primary"],
                 relief=tk.FLAT, font=("Segoe UI", 9),
                 padx=15, pady=5, cursor="hand2").pack(side=tk.LEFT, padx=(0, 10))

        tk.Button(queue_btn_frame, text="Clear Queue", command=self._clear_queue,
                 bg=ModernTheme.COLORS["bg_tertiary"],
                 fg=ModernTheme.COLORS["text_primary"],
                 activebackground=ModernTheme.COLORS["error"],
                 activeforeground=ModernTheme.COLORS["text_primary"],
                 relief=tk.FLAT, font=("Segoe UI", 9),
                 padx=15, pady=5, cursor="hand2").pack(side=tk.LEFT)

        # Log Section
        ttk.Label(right_frame, text="Activity Log", 
                 font=("Segoe UI", 14, "bold"),
                 style="Modern.TLabel").grid(row=3, column=0, sticky=tk.W, pady=(0, 10))

        log_frame = ttk.Frame(right_frame, style="Card.TFrame")
        log_frame.grid(row=4, column=0, sticky="nsew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD,
                               bg=ModernTheme.COLORS["bg_card"],
                               fg=ModernTheme.COLORS["text_secondary"],
                               insertbackground=ModernTheme.COLORS["text_primary"],
                               relief=tk.FLAT, font=("Consolas", 9),
                               padx=10, pady=10, height=10)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=10)

        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.grid(row=0, column=1, sticky="ns", pady=10)

        # Progress bar at bottom of right panel
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(right_frame, variable=self.progress_var,
                                           maximum=100, mode="determinate",
                                           style="Modern.Horizontal.TProgressbar", length=400)
        self.progress_bar.grid(row=5, column=0, sticky="ew", pady=(15, 0))

        self.eta_label = ttk.Label(right_frame, text="Ready", 
                                  style="Modern.TLabel",
                                  font=("Segoe UI", 10))
        self.eta_label.grid(row=6, column=0, sticky=tk.W, pady=(5, 0))

    def _build_status_bar(self):
        """Build status bar"""
        status_frame = ttk.Frame(self.main_container, style="Modern.TFrame")
        status_frame.pack(fill=tk.X, pady=(15, 0))

        self.status_label = ttk.Label(status_frame, text="Ready", 
                                     style="Modern.TLabel",
                                     font=("Segoe UI", 9))
        self.status_label.pack(side=tk.LEFT)

        self.version_label = ttk.Label(status_frame, text="v2.0 Pro", 
                                      style="Modern.TLabel",
                                      font=("Segoe UI", 9),
                                      foreground=ModernTheme.COLORS["text_muted"])
        self.version_label.pack(side=tk.RIGHT)

    def _load_settings(self):
        """Load saved settings"""
        self.preset_var.set(self.settings.get("default_preset", "balanced"))
        self.gpu_var.set(self.settings.get("default_gpu", "auto"))
        self.fps_var.set(self.settings.get("default_fps", 60))

    def _detect_gpu(self):
        """Detect GPU and update badge"""
        try:
            gpu_type = GPUManager.detect_gpu()
            config = GPUManager.get_config(gpu_type)
            self.gpu_badge.config(text=f"  {config.name}  ")
            self._log(f"Detected GPU: {config.name}")
        except Exception as e:
            self.gpu_badge.config(text="  CPU Only  ")
            self._log(f"GPU detection failed: {e}")

    def _browse_input(self):
        """Browse for input file"""
        filetypes = [
            ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm"),
            ("All files", "*.*")
        ]
        filename = filedialog.askopenfilename(
            initialdir=self.settings.get("last_input_dir"),
            title="Select Video File",
            filetypes=filetypes
        )
        if filename:
            self.input_var.set(filename)
            self.settings.set("last_input_dir", os.path.dirname(filename))
            self._update_video_info(filename)

            # Auto-generate output path
            base, ext = os.path.splitext(filename)
            output_path = f"{base}_enhanced{ext}"
            self.output_var.set(output_path)

    def _browse_output(self):
        """Browse for output file"""
        filename = filedialog.asksaveasfilename(
            initialdir=self.settings.get("last_output_dir"),
            title="Save Enhanced Video",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4"), ("MKV video", "*.mkv"), ("All files", "*.*")]
        )
        if filename:
            self.output_var.set(filename)
            self.settings.set("last_output_dir", os.path.dirname(filename))

    def _update_video_info(self, filepath: str):
        """Update video info display"""
        try:
            info = self.ffmpeg.get_video_info(filepath)
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = stream.get("width", "?")
                    height = stream.get("height", "?")
                    fps_str = stream.get("r_frame_rate", "?")
                    duration = info.get("format", {}).get("duration", "?")

                    if fps_str != "?" and "/" in fps_str:
                        num, den = fps_str.split("/")
                        fps = round(int(num) / int(den), 2) if int(den) != 0 else "?"
                    else:
                        fps = fps_str

                    if duration != "?":
                        mins = int(float(duration) / 60)
                        secs = int(float(duration) % 60)
                        duration_str = f"{mins}:{secs:02d}"
                    else:
                        duration_str = "?"

                    info_text = f"{width}x{height} • {fps}fps • {duration_str}"
                    self.video_info_label.config(text=info_text, fg=ModernTheme.COLORS["text_secondary"])
                    return
        except:
            pass

        self.video_info_label.config(text="Unable to read video info", fg=ModernTheme.COLORS["error"])

    def _add_to_queue(self):
        """Add current settings to queue"""
        input_path = self.input_var.get()
        output_path = self.output_var.get()

        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("Error", "Please select a valid input video file.")
            return

        if not output_path:
            messagebox.showerror("Error", "Please specify an output file path.")
            return

        task = VideoTask(
            input_path=input_path,
            output_path=output_path,
            target_fps=self.fps_var.get(),
            upscale=self.upscale_var.get() or None,
            preset=self.preset_var.get(),
            gpu_type=self.gpu_var.get()
        )

        self.tasks.append(task)
        self.task_queue.put(task)

        # Add to treeview
        filename = os.path.basename(input_path)
        upscale_str = task.upscale if task.upscale else "None"
        self.queue_tree.insert("", tk.END, values=(
            filename, task.target_fps, upscale_str, 
            task.preset, "Pending", "0%"
        ))

        self._log(f"Added to queue: {filename} -> {task.target_fps}fps")
        self._update_status(f"Queue: {len(self.tasks)} task(s)")

    def _remove_selected(self):
        """Remove selected item from queue"""
        selected = self.queue_tree.selection()
        if not selected:
            return

        for item in selected:
            idx = self.queue_tree.index(item)
            if idx < len(self.tasks):
                self.tasks.pop(idx)
            self.queue_tree.delete(item)

        self._update_status(f"Queue: {len(self.tasks)} task(s)")

    def _clear_queue(self):
        """Clear all tasks from queue"""
        self.tasks.clear()
        while not self.task_queue.empty():
            self.task_queue.get()

        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)

        self._update_status("Queue cleared")

    def _start_processing(self):
        """Start processing queue"""
        if not self.tasks:
            messagebox.showwarning("Warning", "Queue is empty. Add tasks first.")
            return

        if self.processing:
            return

        self.processing = True
        self.start_btn.config(state=tk.DISABLED, text="Processing...")
        self.stop_btn.config(state=tk.NORMAL)
        self.add_btn.config(state=tk.DISABLED)

        self.process_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.process_thread.start()

    def _stop_processing(self):
        """Stop processing"""
        self.processing = False
        self._update_status("Stopping...")

    def _process_queue(self):
        """Process tasks in queue"""
        for i, task in enumerate(self.tasks):
            if not self.processing:
                break

            if task.status in ["completed", "failed"]:
                continue

            self.current_task = task
            task.status = "processing"

            # Update treeview
            self.root.after(0, lambda idx=i: self._update_task_status(idx, "Processing", "0%"))
            self.root.after(0, lambda: self._update_status(f"Processing {i+1}/{len(self.tasks)}: {os.path.basename(task.input_path)}"))

            try:
                gpu_config = GPUManager.get_config(task.gpu_type)

                success = self.ffmpeg.run_with_progress(
                    task, gpu_config,
                    progress_callback=lambda p, e, idx=i: self.root.after(0, lambda: self._update_progress(idx, p, e)),
                    log_callback=lambda msg: self.root.after(0, lambda: self._log(msg))
                )

                if success:
                    task.status = "completed"
                    task.progress = 100.0
                    self.root.after(0, lambda idx=i: self._update_task_status(idx, "Completed", "100%"))
                    self._log(f"\n✓ Completed: {os.path.basename(task.output_path)}\n")
                else:
                    task.status = "failed"
                    self.root.after(0, lambda idx=i: self._update_task_status(idx, "Failed", "Error"))
                    self._log(f"\n✗ Failed: {os.path.basename(task.input_path)}\n")

            except Exception as e:
                task.status = "failed"
                task.error_msg = str(e)
                self.root.after(0, lambda idx=i: self._update_task_status(idx, "Failed", "Error"))
                self._log(f"\n✗ Error: {str(e)}\n")

        self.root.after(0, self._processing_finished)

    def _update_progress(self, task_idx: int, progress: float, eta: str):
        """Update progress display"""
        self.progress_var.set(progress)
        self.eta_label.config(text=f"Progress: {progress:.1f}% | ETA: {eta}")

        # Update treeview
        children = self.queue_tree.get_children()
        if task_idx < len(children):
            item = children[task_idx]
            values = list(self.queue_tree.item(item, "values"))
            values[5] = f"{progress:.1f}%"
            self.queue_tree.item(item, values=values)

    def _update_task_status(self, task_idx: int, status: str, progress_str: str):
        """Update task status in treeview"""
        children = self.queue_tree.get_children()
        if task_idx < len(children):
            item = children[task_idx]
            values = list(self.queue_tree.item(item, "values"))
            values[4] = status
            values[5] = progress_str
            self.queue_tree.item(item, values=values)

            # Color coding
            if status == "Completed":
                self.queue_tree.tag_configure("completed", foreground=ModernTheme.COLORS["success"])
                self.queue_tree.item(item, tags=("completed",))
            elif status == "Failed":
                self.queue_tree.tag_configure("failed", foreground=ModernTheme.COLORS["error"])
                self.queue_tree.item(item, tags=("failed",))
            elif status == "Processing":
                self.queue_tree.tag_configure("processing", foreground=ModernTheme.COLORS["accent"])
                self.queue_tree.item(item, tags=("processing",))

    def _processing_finished(self):
        """Called when processing is finished"""
        self.processing = False
        self.start_btn.config(state=tk.NORMAL, text="▶ Start Processing")
        self.stop_btn.config(state=tk.DISABLED)
        self.add_btn.config(state=tk.NORMAL)
        self.progress_var.set(0)
        self.eta_label.config(text="Ready")
        self._update_status("Processing complete")

        completed = sum(1 for t in self.tasks if t.status == "completed")
        failed = sum(1 for t in self.tasks if t.status == "failed")

        if failed == 0:
            messagebox.showinfo("Complete", f"All tasks completed successfully! ({completed} videos)")
        else:
            messagebox.showwarning("Complete", f"Processing finished.\nCompleted: {completed}\nFailed: {failed}")

    def _log(self, message: str):
        """Add message to log"""
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)

    def _update_status(self, message: str):
        """Update status bar"""
        self.status_label.config(text=message)


def main():
    """Main entry point"""
    # Check for CLI mode
    if len(sys.argv) > 1 and sys.argv[1] in ["--cli", "-c"]:
        # CLI mode - use original functionality
        parser = argparse.ArgumentParser(
            description="Video Enhancer Pro - CLI Mode",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Examples:
  %(prog)s input.mp4 output.mp4 60
  %(prog)s input.mp4 output.mp4 60 --upscale 2x
  %(prog)s input.mp4 output.mp4 120 --gpu amd --preset quality
            """
        )

        parser.add_argument("input", help="Input video file")
        parser.add_argument("output", help="Output video file")
        parser.add_argument("fps", type=int, help="Target frame rate (e.g., 60, 120)")
        parser.add_argument("--gpu", default="auto", help="GPU type (auto/nvidia/amd/intel/cpu/apple)")
        parser.add_argument("--preset", default="balanced", choices=["fast", "balanced", "quality"])
        parser.add_argument("--upscale", help="Upscale resolution (e.g., '2x', '1920x1080', '4K')")

        args = parser.parse_args()

        try:
            ffmpeg = FFmpegManager()
            gpu_config = GPUManager.get_config(args.gpu)

            task = VideoTask(
                input_path=args.input,
                output_path=args.output,
                target_fps=args.fps,
                upscale=args.upscale,
                preset=args.preset,
                gpu_type=args.gpu
            )

            def print_progress(p, e):
                print(f"\rProgress: {p:.1f}% | ETA: {e}", end="", flush=True)

            def print_log(msg):
                print(msg, end="")

            print(f"Processing: {args.input}")
            print(f"Output: {args.output}")
            print(f"Target FPS: {args.fps}")
            print(f"GPU: {gpu_config.name}")
            print(f"Preset: {args.preset}")
            if args.upscale:
                print(f"Upscale: {args.upscale}")
            print("-" * 50)

            success = ffmpeg.run_with_progress(task, gpu_config, print_progress, print_log)
            print()

            if success:
                print("✓ Enhancement complete!")
                sys.exit(0)
            else:
                print("✗ Enhancement failed!")
                sys.exit(1)

        except Exception as e:
            print(f"Error: {e}")
            sys.exit(1)

    else:
        # GUI mode
        root = tk.Tk()
        app = VideoEnhancerGUI(root)
        root.mainloop()


if __name__ == "__main__":
    main()
