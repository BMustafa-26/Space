#!/usr/bin/env python3
"""Low-latency Linux screen streaming and remote touch input server.

This module is intentionally a clean, documented skeleton:
- FFmpeg captures the Linux desktop and streams H.264 over UDP to Android.
- An asyncio UDP/TCP input listener accepts "X,Y,ACTION" messages.
- Input injection is isolated behind placeholder functions using xdotool/ydotool.

Production hardening checklist:
- Add authentication and encryption before using on untrusted networks.
- Calibrate Android display coordinates to Linux desktop resolution.
- Support Wayland capture/input paths separately from X11.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import subprocess
from dataclasses import dataclass
from typing import Optional

VIDEO_PORT = 5000
INPUT_PORT = 5001
DEFAULT_DISPLAY = ":0.0"
DEFAULT_RESOLUTION = "1920x1080"
DEFAULT_FRAMERATE = 60


@dataclass(frozen=True)
class ServerConfig:
    """Runtime settings shared by stream and input modules."""

    client_ip: str
    video_port: int = VIDEO_PORT
    input_port: int = INPUT_PORT
    display: str = DEFAULT_DISPLAY
    resolution: str = DEFAULT_RESOLUTION
    framerate: int = DEFAULT_FRAMERATE
    encoder: str = "libx264"  # Optional NVIDIA path: "h264_nvenc"
    use_tcp_input: bool = False


class ScreenStreamer:
    """Starts and supervises an FFmpeg ultra-low-latency UDP H.264 stream."""

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.process: Optional[subprocess.Popen[bytes]] = None

    def build_ffmpeg_command(self) -> list[str]:
        """Build an FFmpeg command tuned for LAN latency rather than quality."""
        destination = f"udp://{self.config.client_ip}:{self.config.video_port}?pkt_size=1316"

        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "x11grab",
            "-draw_mouse",
            "1",
            "-video_size",
            self.config.resolution,
            "-framerate",
            str(self.config.framerate),
            "-i",
            self.config.display,
            "-an",
            "-c:v",
            self.config.encoder,
        ]

        if self.config.encoder == "h264_nvenc":
            # NVIDIA NVENC low-latency preset path. Requires compatible NVIDIA driver/GPU.
            command += [
                "-preset",
                "p1",
                "-tune",
                "ull",
                "-zerolatency",
                "1",
                "-rc",
                "cbr",
                "-b:v",
                "8M",
            ]
        else:
            # CPU x264 path: ultrafast + zerolatency minimizes encode delay.
            command += [
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-b:v",
                "8M",
                "-x264-params",
                "keyint=30:min-keyint=30:scenecut=0",
            ]

        command += [
            "-pix_fmt",
            "yuv420p",
            "-f",
            "mpegts",
            "-flush_packets",
            "1",
            destination,
        ]
        return command

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        """Keep FFmpeg alive until the server is stopped."""
        while not stop_event.is_set():
            try:
                command = self.build_ffmpeg_command()
                logging.info("Starting FFmpeg stream: %s", " ".join(command))
                self.process = subprocess.Popen(command)

                while self.process.poll() is None and not stop_event.is_set():
                    await asyncio.sleep(0.5)

                if stop_event.is_set():
                    break

                logging.warning("FFmpeg exited with code %s; restarting soon", self.process.returncode)
                await asyncio.sleep(1.0)
            except FileNotFoundError:
                logging.exception("FFmpeg was not found. Install ffmpeg and restart the server.")
                await asyncio.sleep(5.0)
            except Exception:
                logging.exception("Unexpected streaming error; keeping server alive")
                await asyncio.sleep(1.0)

        self.stop()

    def stop(self) -> None:
        """Terminate the FFmpeg process gracefully, then forcefully if needed."""
        if self.process and self.process.poll() is None:
            logging.info("Stopping FFmpeg")
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


class InputInjector:
    """Converts Android touch messages into Linux pointer actions.

    The subprocess calls are intentionally placeholders. Choose xdotool for X11 or
    ydotool/uinput for Wayland-capable injection, then adjust coordinate scaling.
    """

    @staticmethod
    def handle_touch_message(message: str) -> None:
        try:
            x_raw, y_raw, action_raw = message.strip().split(",", maxsplit=2)
            x = int(float(x_raw))
            y = int(float(y_raw))
            action = action_raw.strip().upper()
        except ValueError:
            logging.warning("Ignoring malformed input payload: %r", message)
            return

        logging.debug("Touch event: x=%s y=%s action=%s", x, y, action)
        InputInjector.move_pointer(x, y)

        if action == "DOWN":
            InputInjector.mouse_down()
        elif action == "UP":
            InputInjector.mouse_up()
        elif action == "MOVE":
            return
        else:
            logging.warning("Unknown touch action: %s", action)

    @staticmethod
    def move_pointer(x: int, y: int) -> None:
        # X11 example: subprocess.run(["xdotool", "mousemove", str(x), str(y)], check=False)
        # ydotool example: subprocess.run(["ydotool", "mousemove", "--absolute", str(x), str(y)], check=False)
        logging.info("PLACEHOLDER move pointer to (%d, %d)", x, y)

    @staticmethod
    def mouse_down() -> None:
        # X11 example: subprocess.run(["xdotool", "mousedown", "1"], check=False)
        # ydotool example: subprocess.run(["ydotool", "click", "0xC0"], check=False)
        logging.info("PLACEHOLDER mouse down")

    @staticmethod
    def mouse_up() -> None:
        # X11 example: subprocess.run(["xdotool", "mouseup", "1"], check=False)
        logging.info("PLACEHOLDER mouse up")


class TouchUdpProtocol(asyncio.DatagramProtocol):
    """UDP listener for fire-and-forget touch events from Android."""

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        try:
            message = data.decode("utf-8", errors="replace")
            InputInjector.handle_touch_message(message)
        except Exception:
            logging.exception("Failed to process UDP input from %s", addr)


async def run_udp_input_server(config: ServerConfig, stop_event: asyncio.Event) -> None:
    """Run UDP port 5001 listener until cancellation."""
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(
        TouchUdpProtocol,
        local_addr=("0.0.0.0", config.input_port),
    )
    logging.info("Listening for UDP touch input on 0.0.0.0:%d", config.input_port)
    try:
        await stop_event.wait()
    finally:
        transport.close()


async def handle_tcp_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Optional TCP input mode; each line must be X,Y,ACTION."""
    peer = writer.get_extra_info("peername")
    logging.info("TCP input client connected: %s", peer)
    try:
        while line := await reader.readline():
            InputInjector.handle_touch_message(line.decode("utf-8", errors="replace"))
    except Exception:
        logging.exception("TCP input client error: %s", peer)
    finally:
        writer.close()
        await writer.wait_closed()
        logging.info("TCP input client disconnected: %s", peer)


async def run_tcp_input_server(config: ServerConfig, stop_event: asyncio.Event) -> None:
    server = await asyncio.start_server(handle_tcp_client, "0.0.0.0", config.input_port)
    logging.info("Listening for TCP touch input on 0.0.0.0:%d", config.input_port)
    async with server:
        await stop_event.wait()
        server.close()
        await server.wait_closed()


def parse_args() -> ServerConfig:
    parser = argparse.ArgumentParser(description="Linux LAN screen mirror server skeleton")
    parser.add_argument("--client-ip", required=True, help="Android device IP address receiving UDP video")
    parser.add_argument("--video-port", type=int, default=VIDEO_PORT)
    parser.add_argument("--input-port", type=int, default=INPUT_PORT)
    parser.add_argument("--display", default=DEFAULT_DISPLAY, help="X11 display, e.g. :0.0")
    parser.add_argument("--resolution", default=DEFAULT_RESOLUTION, help="Capture size, e.g. 1920x1080")
    parser.add_argument("--framerate", type=int, default=DEFAULT_FRAMERATE)
    parser.add_argument("--encoder", default="libx264", choices=("libx264", "h264_nvenc"))
    parser.add_argument("--tcp-input", action="store_true", help="Use TCP instead of UDP for touch input")
    args = parser.parse_args()
    return ServerConfig(
        client_ip=args.client_ip,
        video_port=args.video_port,
        input_port=args.input_port,
        display=args.display,
        resolution=args.resolution,
        framerate=args.framerate,
        encoder=args.encoder,
        use_tcp_input=args.tcp_input,
    )


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = parse_args()
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    streamer = ScreenStreamer(config)
    input_task = run_tcp_input_server(config, stop_event) if config.use_tcp_input else run_udp_input_server(config, stop_event)

    await asyncio.gather(
        streamer.run_forever(stop_event),
        input_task,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
