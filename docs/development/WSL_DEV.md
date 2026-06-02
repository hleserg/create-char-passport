# Developing on WSL + CUDA

This project does **image generation** and ships a local **Gradio verifier**, so the
recommended development environment is **WSL2 (Ubuntu) with an NVIDIA CUDA driver**.
Linux also removes Windows-specific friction (non-ASCII paths breaking image I/O,
missing `jq`/`make`, non-portable shell hooks).

## One-time setup

```bash
# In WSL (Ubuntu), with the NVIDIA driver installed on Windows and `nvidia-smi` working:
curl -LsSf https://astral.sh/uv/install.sh | sh   # install uv if absent
uv sync --all-extras                              # create .venv, install deps
uv run pre-commit install                         # repo hooks
make check                                         # DoD gate — must be green
```

## Exposing the Gradio verifier (or any local UI) to the LAN — WSL networking

> **THE RULE: a WSL service must listen on `0.0.0.0` inside WSL, never `127.0.0.1`.**

Windows reaches a WSL service through the WSL distro's **eth0 IP** (e.g.
`172.22.x.x`) via a `netsh portproxy`. A service bound to WSL **loopback**
(`127.0.0.1`) is invisible to that proxy and unreachable from the host or the LAN.
So launch the verifier / any server bound to `0.0.0.0` (expose a `*_HOST` setting
defaulting to `0.0.0.0`).

**Reaching it from the Windows host / another LAN machine (Windows 10):**

> WSL **mirrored networking** (`networkingMode=mirrored`, no portproxy needed)
> requires **Windows 11 22H2+**. On Windows 10 that `.wslconfig` line is silently
> ignored and WSL falls back to NAT, so you need a host-side portproxy + firewall.

```powershell
# Elevated PowerShell. Re-derive the WSL IP (it changes when WSL restarts):
$ip = (wsl hostname -I).Trim().Split(' ')[0]; "WSL IP = $ip"
$port = 7860
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$port 2>$null
netsh interface portproxy add    v4tov4 listenaddress=0.0.0.0 listenport=$port connectaddress=$ip connectport=$port
netsh advfirewall firewall delete rule name=WSL_LAN_$port 2>$null
netsh advfirewall firewall add    rule name=WSL_LAN_$port dir=in action=allow protocol=TCP localport=$port remoteip=LocalSubnet
```

Then open `http://<windows-LAN-IP>:<port>` from any machine on the subnet (or
`localhost:<port>` on the host). To survive reboots/WSL restarts, drive that script
from a Scheduled Task on logon + a short interval; `schtasks /Create` is more robust
than `Register-ScheduledTask` on localized / non-domain Windows. Prefer a LAN-scoped
(`remoteip=LocalSubnet`) firewall rule over disabling the firewall.

## Keep the code OS-agnostic

- **Never call image/file I/O with a raw path that may be non-ASCII** — prefer
  Pillow (`Image.open`) or decode via `np.fromfile` + `cv2.imdecode` if OpenCV is used.
- Prefer pure stdlib path handling; don't hardcode shell tools in committed code.
