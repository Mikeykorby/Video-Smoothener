#!/usr/bin/env python3
"""
Video Smoothener / Universal Video Enhancer
A Python script that uses FFmpeg to make videos smoother.

Features:
- Frame Interpolation: Increase frame rate using motion compensation.
- GPU Acceleration: Supports NVIDIA (NVENC), AMD (AMF/VCE), Intel (QSV), and CPU.
- Upscaling: Increase video resolution (e.g., 2x, 4K).
- Quality Presets: Choose between fast, balanced, and quality modes.

Repository: https://github.com/Mikeykorby/Video-Smoothener.git
"""

import argparse
import subprocess
import sys
import os
import shutil
import json
from pathlib import Path
from typing import Optional, List, Tuple


class GPUConfig:
    """GPU configuration for different vendors"""
    
    def __init__(self, name: str, encoder: str, decoder: Optional[str], 
                 scale_filter: str, supported: bool = True):
        self.name = name
        self.encoder = encoder
        self.decoder = decoder
        self.scale_filter = scale_filter
        self.supported = supported
    
    def __repr__(self):
        return f"GPUConfig({self.name}, encoder={self.encoder}, supported={self.supported})"


class VideoEnhancer:
    """Main video enhancement class with GPU acceleration support"""
    
    # Preset configurations for quality/speed tradeoff
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
    
    # GPU configurations for different vendors
    GPU_CONFIGS = {
        # NVIDIA GPUs (GTX 600+, RTX series)
        "nvidia": GPUConfig(
            name="NVIDIA",
            encoder="h264_nvenc",
            decoder="h264_cuvid",
            scale_filter="hwupload_cuda,scale_cuda={width}:{height}:interp_algo=lanczos,hwdownload,format=nv12"
        ),
        
        # AMD GPUs (RX 580, Vega, RX 5000/6000/7000 series)
        "amd": GPUConfig(
            name="AMD",
            encoder="h264_amf",  # AMF encoder for older and newer AMD cards
            decoder=None,  # AMF doesn't have a specific decoder
            scale_filter="scale={width}:{height}:flags=lanczos:format=yuv420p"
        ),
        
        # Intel GPUs (HD, Iris, Arc)
        "intel": GPUConfig(
            name="Intel",
            encoder="h264_qsv",
            decoder="h264_qsv",
            scale_filter="scale={width}:{height}:flags=lanczos:format=yuv420p"
        ),
        
        # CPU fallback
        "cpu": GPUConfig(
            name="CPU",
            encoder="libx264",
            decoder=None,
            scale_filter="scale={width}:{height}:flags={scale_flags}:format=yuv420p"
        )
    }
    
    def __init__(self, gpu_type: str = "auto", preset: str = "balanced"):
        self.gpu_type = gpu_type.lower()
        self.preset_name = preset.lower()
        self.preset = self.PRESETS.get(self.preset_name, self.PRESETS["balanced"])
        self.gpu_config = None
        self.ffmpeg_path = self._find_ffmpeg()
        
    def _find_ffmpeg(self) -> str:
        """Find FFmpeg executable"""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            # Try common locations on Windows
            common_paths = [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
                os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
            ]
            for path in common_paths:
                if os.path.isfile(path):
                    return path
            raise RuntimeError(
                "FFmpeg not found! Please install FFmpeg and add it to PATH.\n"
                "Download from: https://ffmpeg.org/download.html"
            )
        return ffmpeg
    
    def detect_gpu(self) -> str:
        """Auto-detect GPU type"""
        if self.gpu_type != "auto":
            return self.gpu_type
        
        print("Detecting GPU...")
        
        # Check for NVIDIA
        try:
            result = subprocess.run(
                ["nvidia-smi"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print("  + NVIDIA GPU detected")
                return "nvidia"
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        # Check for AMD (Windows)
        try:
            # Check for AMD GPU via dxdiag or other means
            import ctypes
            if ctypes.windll:
                # Try to detect AMD through driver info
                try:
                    result = subprocess.run(
                        ["wmic", "path", "win32_VideoController", "get", "Name"],
                        capture_output=True, text=True, timeout=10
                    )
                    if "AMD" in result.stdout or "Radeon" in result.stdout or "RX" in result.stdout:
                        print("  + AMD GPU detected")
                        return "amd"
                except:
                    pass
        except:
            pass
        
        # Check for Intel (QSV)
        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", 
                 "-init_hw_device", "qsv", "-f", "lavfi", "-i", "nullsrc", 
                 "-frames:v", "0", "-f", "null", "-"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                print("  + Intel QSV detected")
                return "intel"
        except:
            pass
        
        print("  + No dedicated GPU detected, using CPU")
        return "cpu"
    
    def setup_gpu(self) -> GPUConfig:
        """Setup GPU configuration"""
        detected = self.detect_gpu()
        
        if detected in self.GPU_CONFIGS:
            self.gpu_config = self.GPU_CONFIGS[detected]
            print(f"Using {self.gpu_config.name} ({detected.upper()}) for acceleration")
        else:
            print(f"Unknown GPU type '{detected}', falling back to CPU")
            self.gpu_config = self.GPU_CONFIGS["cpu"]
        
        return self.gpu_config
    
    def get_video_info(self, input_path: str) -> dict:
        """Get video information using ffprobe"""
        ffprobe = self.ffmpeg_path.replace("ffmpeg", "ffprobe")
        
        cmd = [
            ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            input_path
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(result.stdout)
        except subprocess.CalledProcessError as e:
            print(f"Error getting video info: {e}")
            return {}
    
    def get_video_dimensions(self, input_path: str) -> Tuple[int, int]:
        """Get video width and height"""
        info = self.get_video_info(input_path)
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                return stream.get("width", 1920), stream.get("height", 1080)
        return 1920, 1080
    
    def build_filter_complex(self, target_fps: int, upscale: Optional[str] = None) -> str:
        """Build FFmpeg filter complex string"""
        filters = []
        
        # Motion Interpolation (smooth FPS)
        # mi_mode=mci = motion compensated interpolation (best quality)
        # mc_mode=aobmc = adaptive overlapped block motion compensation
        # me_mode=bidir = bidirectional motion estimation
        complexity = self.preset["minterpolate_complexity"]
        
        if complexity == "low":
            # Faster but lower quality interpolation
            mi_filter = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=fast_bilinear:me_mode={self.preset['minterpolate_search']}'"
        elif complexity == "medium":
            # Balanced
            mi_filter = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode={self.preset['minterpolate_search']}'"
        else:
            # High quality - slower but better
            mi_filter = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode={self.preset['minterpolate_search']}:me=epzs'"
        
        filters.append(mi_filter)
        
        # Upscaling
        if upscale:
            width, height = self.parse_upscale(upscale)
            if self.gpu_config.name == "NVIDIA" and self.gpu_type != "cpu":
                # CUDA scaling for NVIDIA
                scale_filter = f"hwupload_cuda,scale_cuda={width}:{height}:interp_algo=lanczos,hwdownload,format=nv12"
            else:
                # CPU/AMD/Intel scaling
                scale_flags = self.preset["scale_flags"]
                scale_filter = f"scale={width}:{height}:flags={scale_flags}:format=yuv420p"
            filters.append(scale_filter)
        
        # Color format conversion (ensure compatibility)
        filters.append("format=yuv420p")
        
        return ",".join(filters)
    
    def parse_upscale(self, upscale_str: str) -> Tuple[int, int]:
        """Parse upscale parameter (e.g., '2x', '1920x1080', '4K')"""
        upscale_lower = upscale_str.lower()
        
        # Common presets
        presets = {
            "720p": (1280, 720),
            "1080p": (1920, 1080),
            "1440p": (2560, 1440),
            "2k": (2560, 1440),
            "4k": (3840, 2160),
            "2160p": (3840, 2160),
        }
        
        if upscale_lower in presets:
            return presets[upscale_lower]
        
        # Check for multiplier (e.g., "2x")
        if upscale_lower.endswith("x"):
            try:
                multiplier = float(upscale_lower[:-1])
                # We need the original dimensions, this will be handled in the calling method
                # For now, return a flag to use original dimensions * multiplier
                return (int(multiplier * 1000), 0)  # Special marker
            except ValueError:
                pass
        
        # Check for resolution format (e.g., "1920x1080")
        if "x" in upscale_str:
            try:
                parts = upscale_str.split("x")
                return (int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
        
        raise ValueError(f"Invalid upscale format: {upscale_str}. Use '2x', '1920x1080', '4K', etc.")
    
    def get_upscale_dimensions(self, input_path: str, upscale_str: str) -> Tuple[int, int]:
        """Get final dimensions considering upscale factor"""
        orig_w, orig_h = self.get_video_dimensions(input_path)
        
        upscale_lower = upscale_str.lower()
        
        # Check for multiplier format
        if upscale_lower.endswith("x"):
            try:
                multiplier = float(upscale_lower[:-1])
                return (int(orig_w * multiplier), int(orig_h * multiplier))
            except ValueError:
                pass
        
        # Direct resolution
        try:
            return self.parse_upscale(upscale_str)
        except ValueError:
            pass
        
        return (orig_w, orig_h)
    
    def build_command(self, input_path: str, output_path: str, target_fps: int, 
                     upscale: Optional[str] = None, audio_codec: str = "aac") -> List[str]:
        """Build the FFmpeg command"""
        
        # Setup GPU
        self.setup_gpu()
        
        cmd = [self.ffmpeg_path]
        
        # Input options
        cmd.extend(["-i", input_path])
        
        # Video filter for motion interpolation and optional upscaling
        if upscale:
            # Get final dimensions
            final_w, final_h = self.get_upscale_dimensions(input_path, upscale)
            
            # Build complex filter
            filters = []
            
            # Motion interpolation
            complexity = self.preset["minterpolate_complexity"]
            if complexity == "low":
                mi_filter = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=fast_bilinear:me_mode=bidir'"
            elif complexity == "medium":
                mi_filter = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir'"
            else:
                mi_filter = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=epzs'"
            
            filters.append(mi_filter)
            
            # Upscaling with lanczos/splinereserve for better quality
            scale_flags = self.preset["scale_flags"]
            if self.gpu_config.name == "NVIDIA":
                # Use CUDA for scaling if on NVIDIA
                scale_filter = f"scale={final_w}:{final_h}:flags={scale_flags}:format=yuv420p"
            else:
                scale_filter = f"scale={final_w}:{final_h}:flags={scale_flags}:format=yuv420p"
            
            filters.append(scale_filter)
            
            # Sharpening for upscaled video to enhance details
            if self.preset_name == "quality":
                filters.append("unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=1.0")
            
            # Combine filters
            vf = ",".join(filters)
            cmd.extend(["-vf", vf])
        else:
            # Only FPS interpolation
            complexity = self.preset["minterpolate_complexity"]
            if complexity == "low":
                vf = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=fast_bilinear:me_mode=bidir'"
            elif complexity == "medium":
                vf = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir'"
            else:
                vf = f"minterpolate='fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:me=epzs'"
            
            cmd.extend(["-vf", vf])
        
        # Video encoding settings
        encoder = self.gpu_config.encoder
        cmd.extend(["-c:v", encoder])
        
        # Encoder-specific settings
        if self.gpu_config.name == "NVIDIA":
            # NVIDIA NVENC settings
            cmd.extend([
                "-preset", self.preset["preset"],
                "-cq", self.preset["crf"],
            ])
        elif self.gpu_config.name == "AMD":
            # AMD AMF settings (for RX 580 and newer)
            # AMD AMF uses different quality settings
            quality_setting = "quality" if self.preset_name == "quality" else "speed" if self.preset_name == "fast" else "balanced"
            cmd.extend([
                "-quality", quality_setting,
                "-rc", "cqp",
                "-qp_p", self.preset["crf"],
                "-qp_i", self.preset["crf"],
            ])
        elif self.gpu_config.name == "Intel":
            # Intel QSV settings
            cmd.extend([
                "-preset", self.preset["preset"],
                "-global_quality", self.preset["crf"],
            ])
        else:
            # CPU x264 settings
            cmd.extend([
                "-preset", self.preset["preset"],
                "-crf", self.preset["crf"],
            ])
        
        # Force target FPS
        cmd.extend(["-r", str(target_fps)])
        
        # Audio settings (copy by default for speed)
        cmd.extend(["-c:a", audio_codec, "-b:a", "320k"])
        
        # Pixel format
        cmd.extend(["-pix_fmt", "yuv420p"])
        
        # Output file (overwrite if exists)
        cmd.append("-y")
        cmd.append(output_path)
        
        return cmd
    
    def enhance(self, input_path: str, output_path: str, target_fps: int,
                upscale: Optional[str] = None) -> bool:
        """Run the video enhancement process"""
        
        # Validate input
        if not os.path.isfile(input_path):
            print(f"Error: Input file not found: {input_path}")
            return False
        
        # Round target FPS to a reasonable value
        if target_fps < 1:
            print("Error: FPS must be at least 1")
            return False
        
        print(f"\n{'='*60}")
        print(f"Video Enhancement - {self.preset['description']}")
        print(f"{'='*60}")
        print(f"Input:  {input_path}")
        print(f"Output: {output_path}")
        print(f"Target FPS: {target_fps}")
        if upscale:
            print(f"Upscale: {upscale}")
        print(f"{'='*60}\n")
        
        # Build and run command
        cmd = self.build_command(input_path, output_path, target_fps, upscale)
        
        print("Running FFmpeg...")
        print(f"Command: {' '.join(cmd)}\n")
        
        try:
            result = subprocess.run(cmd, check=True, capture_output=False, text=True)
            print(f"\nSuccess! Enhanced video saved to: {output_path}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"\nFFmpeg error occurred (code {e.returncode})")
            if e.stdout:
                print(f"STDOUT: {e.stdout}")
            if e.stderr:
                print(f"STDERR: {e.stderr}")
            return False
        except KeyboardInterrupt:
            print("\nProcess interrupted by user")
            return False


def list_presets():
    """Display available quality presets"""
    print("\nAvailable Quality Presets:")
    print("-" * 40)
    for name, config in VideoEnhancer.PRESETS.items():
        print(f"  {name:12} - {config['description']}")
    print()


def list_gpus():
    """Display available GPU options"""
    print("\nAvailable GPU Options:")
    print("-" * 40)
    print("  auto    - Auto-detect GPU (default)")
    print("  nvidia  - NVIDIA GPU (NVENC)")
    print("  amd     - AMD GPU (AMF/VCE) - supports RX 580+")
    print("  intel   - Intel GPU (QSV)")
    print("  cpu     - CPU only (x264)")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Universal Video Enhancer - Smooth & Upscale videos using FFmpeg",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s input.mp4 output.mp4 60
  %(prog)s input.mp4 output.mp4 60 --upscale 2x
  %(prog)s input.mp4 output.mp4 120 --gpu amd --preset quality
  %(prog)s input.mp4 output.mp4 60 --upscale 1920x1080 --preset fast
        """
    )
    
    parser.add_argument("input", help="Input video file")
    parser.add_argument("output", help="Output video file")
    parser.add_argument("fps", type=int, help="Target frame rate (e.g., 60, 120)")
    
    parser.add_argument("--gpu", default="auto",
                        help="GPU type to use (default: auto)")
    parser.add_argument("--preset", default="balanced",
                        choices=["fast", "balanced", "quality"],
                        help="Quality preset (default: balanced)")
    parser.add_argument("--upscale",
                        help="Upscale resolution (e.g., '2x', '1920x1080', '4K')")
    parser.add_argument("--list-presets", action="store_true",
                        help="List available quality presets")
    parser.add_argument("--list-gpus", action="store_true",
                        help="List available GPU options")
    
    args = parser.parse_args()
    
    # Handle info flags
    if args.list_presets:
        list_presets()
        return
    
    if args.list_gpus:
        list_gpus()
        return
    
    # Create enhancer and run
    try:
        enhancer = VideoEnhancer(gpu_type=args.gpu, preset=args.preset)
        success = enhancer.enhance(args.input, args.output, args.fps, args.upscale)
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
