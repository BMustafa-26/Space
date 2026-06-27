# Space LAN Mirror Skeleton

Open-source skeleton for a low-latency Linux-to-Android LAN screen mirror and touch-control project.

## Components

- `pc_server/`: Python asyncio Linux server that launches FFmpeg for H.264 UDP screen streaming and listens for touch input on port `5001`.
- `android_client/`: Android Studio Kotlin skeleton that connects to a PC IP, plays the UDP video stream on port `5000`, and sends touch events back to the PC.

> This repository is an architectural starter. Production use requires device-specific tuning, authentication, encryption, screen scaling calibration, and robust lifecycle handling.
