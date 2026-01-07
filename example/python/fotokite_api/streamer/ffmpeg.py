import http.server
import logging
import os
import signal
import socketserver
import subprocess
import sys
import threading
from typing import Any, List, Tuple

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)

""" CORS support for browsers to access HLS streams """


class CORSRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers", "Range, Content-Type, Origin, Accept"
        )
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(200, "ok")
        self.end_headers()


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def start_ffmpeg(rtsp_url: str, hls_dir: str) -> subprocess.Popen[bytes]:
    playlist_path: str = os.path.join(hls_dir, "playlist.m3u8")

    if not os.path.exists(hls_dir):
        os.makedirs(hls_dir)

    cmd: List[str] = [
        "ffmpeg",
        "-fflags",
        "nobuffer",
        "-rtsp_transport",
        "tcp",
        "-i",
        rtsp_url,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-f",
        "hls",
        "-hls_time",
        "2",
        "-hls_list_size",
        "3",
        "-hls_flags",
        "delete_segments+program_date_time",
        "-start_number",
        "1",
        playlist_path,
    ]

    process = subprocess.Popen(
        cmd, stdout=sys.stdout, stderr=sys.stderr, start_new_session=True,
    )
    logging.info(f"Started FFmpeg for {rtsp_url}")
    return process


def start_http_server(
    hls_dir: str, port: int
) -> Tuple[threading.Thread, socketserver.TCPServer]:
    """Starts an HTTP server to serve files from the specified HLS directory with CORS support.

    Args:
        hls_dir: Path to the directory containing HLS files to be served.
        por: Port number on which the HTTP server will listen.

    Returns:
        A tuple containing the thread running the server and the server instance itself.
    """
    os.chdir(hls_dir)

    httpd: ReusableTCPServer = ReusableTCPServer(("", port), CORSRequestHandler)

    def serve() -> None:
        logging.info(f"Serving HLS on http://localhost:{port}/playlist.m3u8")
        try:
            httpd.serve_forever()
        except Exception as e:
            logging.error(f"HTTP server error: {e}")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread, httpd


def main() -> None:
    configs: List[Tuple[str, str, str, int]] = [
        ("Thermal", "rtsp://192.168.2.100:5012/video", "/tmp/hlsThermal", 8082),
        ("Color", "rtsp://192.168.2.100:5010/video", "/tmp/hlsColor", 8083),
    ]

    processes: List[subprocess.Popen[bytes]] = []
    servers: List[socketserver.TCPServer] = []

    for name, rtsp_url, hls_dir, port in configs:
        proc = start_ffmpeg(rtsp_url, hls_dir)
        _, httpd = start_http_server(hls_dir, port)
        processes.append(proc)
        servers.append(httpd)

    def shutdown(_signum: int, _: Any) -> None:
        logging.info("Shutting down all streams...")
        for proc in processes:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                logging.info(f"Stopped FFmpeg process group {os.getpgid(proc.pid)}")
            except Exception as e:
                logging.error(f"Error stopping process: {e}")

        for server in servers:
            server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    signal.pause()


if __name__ == "__main__":
    main()
