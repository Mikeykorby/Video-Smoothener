# Video Smoothener / Universal Video Enhancer

A Python script that uses FFmpeg to make videos smoother by interpolating frames and upscaling resolution. It supports GPU acceleration for NVIDIA, AMD, Intel, and a CPU fallback.

## Features

- **Frame Interpolation**: Increase frame rate (e.g., 30fps to 60fps or 120fps) using motion compensation for smoother playback.
- **GPU Acceleration**:
  - **NVIDIA** (NVENC)
  - **AMD** (AMF/VCE, supports RX 580 and newer)
  - **Intel** (QSV)
  - **CPU** (Libx264 fallback)
- **Upscaling**: Upscale video resolution (e.g., `2x`, `4K`, `1920x1080`).
- **Quality Presets**: Choose between `fast`, `balanced`, and `quality` modes to trade speed for visual fidelity.
- **Automatic GPU Detection**: Automatically detects your GPU or lets you manually specify one.

## Repository

https://github.com/Mikeykorby/Video-Smoothener.git

## Requirements

- [Python 3.7+](https://www.python.org/downloads/)
- [FFmpeg](https://ffmpeg.org/download.html) (must be added to your system's PATH)

### Optional (for GPU acceleration)

- **NVIDIA**: Up-to-date GPU drivers.
- **AMD**: Up-to-date GPU drivers (AMD Software).
- **Intel**: Up-to-date GPU drivers.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Mikeykorby/Video-Smoothener.git
cd Video-Smoothener
```

### 2. Install Python dependencies

There are no external Python packages required (the script only uses the standard library). However, a `requirements.txt` is provided for good practice.

```bash
pip install -r requirements.txt
```

### 3. Install FFmpeg

FFmpeg is a system dependency and must be downloaded manually.

1. Download FFmpeg from the [official website](https://ffmpeg.org/download.html).
2. Extract it to a folder (e.g., `C:\ffmpeg` on Windows).
3. Add the `bin` directory to your system's `PATH` environment variable.

## Usage

### Basic Usage

Increase a video's frame rate to 60 FPS.

```bash
python video_enhancer.py input.mp4 output.mp4 60
```

### Advanced Examples

**Upscaling and FPS increase:**
```bash
python video_enhancer.py input.mp4 output.mp4 120 --upscale 2x
```

**Use a specific GPU and quality preset:**
```bash
python video_enhancer.py input.mp4 output.mp4 60 --gpu amd --preset quality
```

**Upscale to a specific resolution:**
```bash
python video_enhancer.py input.mp4 output.mp4 60 --upscale 1920x1080 --preset fast
```

## Options

| Option | Description | Default |
| :--- | :--- | :--- |
| `--gpu` | Specify the GPU type: `auto`, `nvidia`, `amd`, `intel`, `cpu` | `auto` |
| `--preset` | Quality preset: `fast`, `balanced`, `quality` | `balanced` |
| `--upscale` | Upscale resolution (e.g., `2x`, `4K`, `1920x1080`) | `None` |
| `--list-presets` | List available quality presets | - |
| `--list-gpus` | List available GPU options | - |

### Quality Presets

- **fast**: Quick processing with lower quality. Best for testing settings.
- **balanced**: Good quality at a reasonable speed. Recommended for most use cases.
- **quality**: Best visual quality, but significantly slower due to more complex motion estimation.

### Upscale Formats

- **Multiplier**: `2x`, `3x`
- **Resolution**: `1920x1080`, `2560x1440`, `3840x2160`
- **Preset Alias**: `720p`, `1080p`, `1440p`, `2k`, `4k`

## Troubleshooting

- **`FFmpeg not found`**: Ensure FFmpeg is correctly installed and added to your system's `PATH` environment variable.
- **`GPU not detected`**: You can manually force a GPU with the `--gpu` flag (e.g., `--gpu amd`). If the GPU encoder fails, the script will automatically fall back to CPU encoding (`libx264`), which will be slower.
- **Slow performance with `quality` preset**: The `quality` preset uses more advanced and computationally heavy motion estimation. If it's too slow, try the `balanced` or `fast` preset.

## Contributing

Contributions are welcome! Feel free to submit a pull request or open an issue on the [GitHub repository](https://github.com/Mikeykorby/Video-Smoothener.git).

## License

This project is licensed under the MIT License.
