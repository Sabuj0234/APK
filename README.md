# Meter Reader (Android) - DLMS/COSEM over TCP

Ported from `All_object_hdlc_rev3.py` (TCP/WRAPPER mode only).

| File | Purpose |
|---|---|
| `dlms_core.py` | UI-free DLMS core: TCP transport, AARQ/HLS session, object list, attribute + profile reads |
| `obis_data.py` | Attribute tables + OBIS names, extracted automatically from your script |
| `main.py` | Kivy UI: Connect -> Objects (search) -> Detail / Profile (CSV) -> Log |
| `buildozer.spec` | APK build config |

## 1. Test on the PC first (recommended)
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install kivy gurux-dlms
  .venv\Scripts\python.exe main.py

`pip show gurux-dlms` reports no packages under `Requires` for version 1.0.203.
The app defaults to the supplied IPv6 meter address, port 4059, and MR association;
saved connection settings override these defaults.
Connect to the meter exactly as you do with the Tk tool. Fix any import /
dependency errors here, where they are cheap to debug.

## 2. Build the APK (WSL2 Ubuntu; Buildozer does not run on native Windows)
Run these commands in the Ubuntu/WSL terminal. Build in the Linux home directory,
not under `/mnt/c`, and copy only the app sources (not the Windows `.venv`):

  sudo apt update
  sudo apt install -y build-essential git zip unzip openjdk-17-jdk python3-pip python3-venv python3-dev autoconf libtool pkg-config zlib1g-dev libncurses-dev libffi-dev libssl-dev cmake
  PROJECT="/mnt/c/Users/user/OneDrive - Cabcon India Limited/Desktop/SABUJ OFFICE/TEST PH"
  mkdir -p ~/meter-reader
  cp "$PROJECT"/{main.py,dlms_core.py,obis_data.py,buildozer.spec} ~/meter-reader/
  cd ~/meter-reader
  python3 -m venv .buildozer-venv
  source .buildozer-venv/bin/activate
  python -m pip install --upgrade pip setuptools wheel
  python -m pip install buildozer cython==0.29.33
  buildozer android debug

The first build downloads the Android SDK/NDK and can take a while. The APK is
written to `bin/meterreader-0.1.0-debug.apk`.

## 3. On the phone
Install the APK (allow "unknown sources"). The phone must have an IP route to the meter
(same Wi-Fi / APN / VPN). Enter IP, port (4059), association, keys -> Connect.
Settings are remembered. CSV exports go to the app's private folder (path shown on screen).

## If the build or first run fails
* `ModuleNotFoundError: Cryptodome` / `Crypto` -> the crypto package name gurux uses differs
  from what is in `requirements`; check with `python -c "import gurux_dlms,sys; print(gurux_dlms.__file__)"` and
  `pip show gurux-dlms`, then change `pycryptodome` <-> `pycryptodomex` (or add `cryptography`).
* Any other missing module -> add it to `requirements`.
* `buildozer android logcat` shows the Python traceback.
