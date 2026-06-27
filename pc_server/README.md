# Linux PC Server

## Requirements

- Linux desktop with X11 capture support
- Python 3.10+
- FFmpeg
- `xdotool` or `ydotool` for input injection

## Run

```bash
python3 server.py --client-ip 192.168.1.50
```

Use NVIDIA NVENC when available:

```bash
python3 server.py --client-ip 192.168.1.50 --encoder h264_nvenc
```

Default ports:

- Video UDP stream: `5000`
- Touch input UDP/TCP listener: `5001`
