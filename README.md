# Video Smoothener / Video Enhancer Pro

A powerful desktop application for video smoothing, frame interpolation, and upscaling. Built with Python, FFmpeg, and a modern glassmorphism UI.

## Features

- **Frame Interpolation**: Increase video frame rate (e.g., 30fps to 60fps or 120fps) using high-quality motion compensation.
- **GPU Acceleration**:
  - **NVIDIA** (NVENC)
  - **AMD** (AMF/VCE, supports RX 580 and newer)
  - **Intel** (QSV)
  - **CPU** (Libx264 fallback)
- **Upscaling**: Upscale video resolution (e.g., 1080p to 4K).
- **Customizable Quality**: Choose between `fast`, `balanced`, and `quality` encoding presets.
- **Modern UI**: Native desktop feel with a glassmorphism design.
- **GPU Support**: NVIDIA, AMD (RX 580+), Intel, and CPU fallback.
- **Wallpaper Integration**: Supports a custom `wallpaper.jpg` for the UI background.

## Repository

https://github.com/Mikeykorby/Video-Smoothener.git

## Requirements

- [Python 3.7+](https://www.python.org/downloads/)
- [FFmpeg](https://ffmpeg.org/download.html) (must be added to your system's PATH)

### GPU Acceleration Prerequisites

- **NVIDIA**: Up-to-date GPU drivers.
- **AMD**: Up-to-date GPU drivers (AMD Software).
- **Intel**: Up-to-date GPU drivers.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Mikeykorby/Video-Smoothener.git
cd Video-Smoothener
```

### 2. Install FFmpeg

FFmpeg is a required system dependency. You must download it manually.

1. Download FFmpeg for Windows from the [official website](https://ffmpeg.org/download.html).
2. Extract it to a folder (e.g., `C:/ffmpeg` on Windows).
3. Add the `bin` directory to your system's `PATH` environment variable.

### 3. Run the application

```bash
python video_enhancer.py
```

This will start a local web server and automatically open a native desktop window for the application.

## Usage

1.  **Select Source Media**: Use the browse button to select your video file.
2.  **Configure Settings**:
    - **Target FPS**: Choose your desired output frame rate (e.g., 60, 120).
    - **Upscale Resolution**: Optionally increase the resolution.
    - **Quality Preset**: Select `fast`, `balanced`, or `quality`.
    - **Hardware Config**: Select your GPU or let it auto-detect.
3.  **Add to Queue**: Click the button to start processing.
4.  **Monitor Progress**: Watch the task queue and the output log for real-time updates.

### Advanced Options

You can also trim the video, set a custom video bitrate, and add custom FFmpeg flags under the **Advanced Options** section.

## Troubleshooting

-   **FFmpeg not found**: Ensure FFmpeg is correctly installed and its `bin` directory is in your system's `PATH`.
-   **GPU not detected**: You can manually select your GPU from the **Hardware Config** dropdown.
-   **Slow performance**: The `quality` preset is significantly slower. Try `balanced` or `fast` for quicker results.
-   **Wallpaper support**: Place a `wallpaper.jpg` in the same directory as `video_enhancer.py` for a custom background.

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue on the [GitHub repository](https://github.com/Mikeykorby/Video-Smoothener.git).

## License

This project is licensed under the MIT License.
