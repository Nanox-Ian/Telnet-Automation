
import os
import re
import time
import telnetlib
from pathlib import Path
from datetime import datetime

# ---- Images (screenshot-like) -------------
from PIL import Image, ImageDraw, ImageFont

# =========================
# CONFIGURATION
# =========================
CONFIG = {
    "gateway_ip": "10.129.14.1",         # Entry point
    "username": "admin",
    "password": "n@n0x0604",
    "enable_password": None,             # If you need "enable", put it here; else keep None
    "devices_file": r"C:\telnets\devices.txt",      # File containing target IPs (one per line)
    "command": "show interface status",  # Command to run on each target
    "output_dir": r"C:\telnets",         # Text logs folder (optional)
    "img_dir": r"C:\telnets\img",        # Screenshot PNGs go here
    "telnet_port": 23,
    "connect_timeout": 15,               # increased for robustness
    "op_timeout": 15,                    # Wait/read timeout for prompts/outputs
    "sleep_short": 0.40,                 # Small delay between reads/writes (slightly higher)
    "save_text_logs": False,             # Set to True if you also want .txt logs
}

# =========================
# Helpers for Telnet/IO
# =========================

# Tolerant prompt detector:
# - looks for a line ending with '>', '#', '$', or a closing bracket (common enough),
# - allows either start-of-buffer or any newline before the prompt.
PROMPT_REGEX = re.compile(rb"(?:^|[\r\n])[^\r\n]*([>#\$]|\])\s?$")

def ensure_dirs():
    Path(CONFIG["output_dir"]).mkdir(parents=True, exist_ok=True)
    Path(CONFIG["img_dir"]).mkdir(parents=True, exist_ok=True)

def _expect_any(tn: telnetlib.Telnet, patterns, timeout):
    return tn.expect(patterns, timeout)

def read_until_prompt(tn: telnetlib.Telnet, timeout: float = 5.0):
    """Accumulates bytes until we see a prompt or the timeout elapses."""
    end_time = time.time() + timeout
    buff = b""
    while time.time() < end_time:
        chunk = tn.read_very_eager()
        if chunk:
            buff += chunk
            if PROMPT_REGEX.search(buff):
                break
        else:
            time.sleep(0.1)
    return buff

def send_and_collect(tn: telnetlib.Telnet, cmd: str, timeout: float = 8.0):
    tn.write(cmd.encode("ascii") + b"\r\n")
    time.sleep(CONFIG["sleep_short"])

    collected = b""
    end_time = time.time() + timeout

    while time.time() < end_time:
        chunk = tn.read_very_eager()
        if chunk:
            collected += chunk

            # handle pagination if any
            if b"--More--" in collected or b"[More]" in collected:
                tn.write(b" ")  # send space to continue
                time.sleep(CONFIG["sleep_short"])
                end_time = time.time() + timeout  # extend timeout after pagination
                continue

            # If we see a prompt, stop
            if PROMPT_REGEX.search(collected):
                break
        else:
            if PROMPT_REGEX.search(collected):
                break
            time.sleep(0.1)

    return collected

def negotiate_login(tn: telnetlib.Telnet, username: str, password: str, timeout: float = 15.0):
    """
    Robust login negotiator for Cisco-like devices showing:
      - Banners ('User Access Verification', 'Press ENTER/any key', etc.)
      - Username: (possibly repeated)
      - Password:
      - Final device prompt ending with '>' or '#'
    """

    patterns = [
        re.compile(br"[Uu]ser\s*Access\s*Verification", re.I),   # banner
        re.compile(br"[Pp]ress\s+(ENTER|any\s+key)", re.I),      # press enter
        re.compile(br"[Uu]sername[: ]"),                         # Username:
        re.compile(br"[Ll]ogin[: ]"),                            # login:
        re.compile(br"[Pp]ass(word)?[: ]"),                      # Password:
        PROMPT_REGEX,                                            # final prompt
    ]

    deadline = time.time() + timeout

    # Wake the line at the start
    tn.write(b"\r\n")
    time.sleep(0.4)
    _ = tn.read_very_eager()

    while time.time() < deadline:
        idx, match, text = tn.expect(patterns, timeout=2.5)

        if idx == -1:
            # No match yet—nudge and keep waiting
            tn.write(b"\r\n")
            time.sleep(0.4)
            continue

        # 0) Cisco banner
        if idx == 0:
            tn.write(b"\r\n")
            time.sleep(0.5)
            continue

        # 1) "Press ENTER/any key"
        if idx == 1:
            tn.write(b"\r\n")
            time.sleep(0.5)
            continue

        # 2/3) Username/login prompt
        if idx in (2, 3):
            tn.write(username.encode("ascii") + b"\r\n")
            time.sleep(0.6)
            continue

        # 4) Password prompt
        if idx == 4:
            tn.write(password.encode("ascii") + b"\r\n")
            time.sleep(0.8)
            # Attempt to read until we see a prompt after password
            out = read_until_prompt(tn, timeout=8.0)
            if PROMPT_REGEX.search(out):
                return True
            # If not yet at prompt, keep looping (device may echo or ask again)
            continue

        # 5) Prompt detected
        if idx == 5:
            return True

    # If we get here, we didn't reach a prompt in time
    return False

def enter_enable_if_needed(tn: telnetlib.Telnet, enable_password: str | None, timeout: float = 6.0):
    if not enable_password:
        return
    current = read_until_prompt(tn, timeout=2.0)
    # Are we at user mode (">") but not privileged ("#")?
    if (b">" in current) and (b"#" not in current):
        tn.write(b"enable\r\n")
        time.sleep(CONFIG["sleep_short"])
        idx, match, text = _expect_any(
            tn,
            [re.compile(br"[Pp]assword[: ]"), PROMPT_REGEX],
            timeout=timeout
        )
        if idx == 0:  # asked for enable password
            tn.write(enable_password.encode("ascii") + b"\r\n")
            time.sleep(CONFIG["sleep_short"])
            _ = read_until_prompt(tn, timeout=timeout)

def disable_paging(tn: telnetlib.Telnet):
    """Cisco-style. If your platform differs, we can make this conditional."""
    _ = send_and_collect(tn, "terminal length 0", timeout=CONFIG["op_timeout"])

# =========================
# Text -> Image
# =========================

def save_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8")

def text_to_image(text: str, out_path: Path, font_size=16, padding=20, bg="#0b0f1a", fg="#e6e9ef"):
    # Try a monospaced font; fallback to default
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", font_size)
    except Exception:
        font = ImageFont.load_default()

    # Normalize CRLFs to LF for consistent measurement
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = text.splitlines() or [""]
    # Use a temp image to measure text
    tmp = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(tmp)

    # Calculate width/height
    line_sizes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    widths = [bbox[2] - bbox[0] for bbox in line_sizes]
    heights = [bbox[3] - bbox[1] for bbox in line_sizes]

    width = max(widths + [400]) + 2 * padding
    # Add small spacing (2 px) between lines
    height = max(200, sum(heights) + 2 * padding + 2 * (len(lines) - 1))

    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)

    y = padding
    for i, line in enumerate(lines):
        draw.text((padding, y), line, font=font, fill=fg)
        y += heights[i] + 2

    img.save(out_path)

# =========================
# Main flow
# =========================

def run():
    ensure_dirs()
    out_dir = Path(CONFIG["output_dir"])
    img_dir = Path(CONFIG["img_dir"])
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    # Load device list
    devices_path = Path(CONFIG["devices_file"])
    if not devices_path.exists():
        raise FileNotFoundError(f"Devices file not found: {devices_path}")

    with devices_path.open("r", encoding="utf-8") as f:
        targets = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    print(f"[i] Targets: {targets}")
    print(f"[i] Text logs -> {out_dir} | Screenshots -> {img_dir}")

    # Connect to gateway (entry) host
    print(f"[i] Connecting to gateway {CONFIG['gateway_ip']} ...")
    tn = telnetlib.Telnet(CONFIG["gateway_ip"], CONFIG["telnet_port"], CONFIG["connect_timeout"])

    # Wake the line/banners on initial connect
    tn.write(b"\r\n")
    time.sleep(CONFIG["sleep_short"])
    tn.write(b"\r\n")
    time.sleep(CONFIG["sleep_short"])
    _ = tn.read_very_eager()

    if not negotiate_login(tn, CONFIG["username"], CONFIG["password"], timeout=CONFIG["connect_timeout"]):
        raise RuntimeError("Login to gateway failed.")

    # Optional: enable on gateway if needed
    enter_enable_if_needed(tn, CONFIG["enable_password"], timeout=CONFIG["op_timeout"])
    disable_paging(tn)  # Not strictly needed for inner devices, but harmless

    # Iterate through target devices (nested telnet)
    for ip in targets:
        print(f"[i] Telnet to {ip} from gateway...")
        tn.write(f"telnet {ip}\r\n".encode("ascii"))
        time.sleep(CONFIG["sleep_short"])

        # Wake/clear any banners before trying to parse prompts
        tn.write(b"\r\n")
        time.sleep(CONFIG["sleep_short"])

        if not negotiate_login(tn, CONFIG["username"], CONFIG["password"], timeout=CONFIG["connect_timeout"]):
            print(f"[!] Login failed for {ip}; skipping.")
            # Try to return to gateway cleanly
            tn.write(b"\x03")  # CTRL-C
            time.sleep(0.3)
            tn.write(b"exit\r\n")
            time.sleep(0.5)
            _ = read_until_prompt(tn, timeout=CONFIG["op_timeout"])
            continue

        enter_enable_if_needed(tn, CONFIG["enable_password"], timeout=CONFIG["op_timeout"])
        disable_paging(tn)

        # Run the command and collect output
        print(f"[i] Running '{CONFIG['command']}' on {ip} ...")
        raw = send_and_collect(tn, CONFIG["command"], timeout=CONFIG["op_timeout"])

        # Clean output: strip ANSI escape sequences
        cleaned = raw.decode("utf-8", errors="ignore")
        cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", cleaned)

        # Prepare content
        header = (
            f"Device: {ip}\n"
            f"Command: {CONFIG['command']}\n"
            f"Time:    {datetime.now().isoformat(timespec='seconds')}\n"
            f"{'-'*60}\n"
        )
        content_to_save = header + cleaned

        # File names
        base = f"{ip.replace('.', '_')}_{timestamp}"
        text_file = out_dir / f"{base}.txt"
        img_file = img_dir / f"{base}.png"

        # Save text (optional)
        if CONFIG["save_text_logs"]:
            text_file.write_text(content_to_save, encoding="utf-8")

        # Save image “screenshot”
        text_to_image(content_to_save, img_file)

        print(f"[✓] Saved screenshot: {img_file.name}" + (f" | log: {text_file.name}" if CONFIG["save_text_logs"] else ""))

        # Exit once to return to gateway (do NOT exit the gateway)
        tn.write(b"exit\r\n")
        time.sleep(CONFIG["sleep_short"])
        _ = read_until_prompt(tn, timeout=CONFIG["op_timeout"])

    print("[i] All targets processed. Closing gateway connection.")
    tn.close()  # Do not 'exit' on the gateway; just close socket.
    print("[✓] Done.")

if __name__ == "__main__":
    run()
