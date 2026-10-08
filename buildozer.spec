[app]
title = Meter Reader
package.name = meterreader
package.domain = org.meter
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json
source.exclude_dirs = .venv
version = 0.1.0

requirements = python3,kivy==2.3.0

orientation = portrait
fullscreen = 0

android.permissions = INTERNET,ACCESS_NETWORK_STATE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.allow_backup = False

[buildozer]
log_level = 2
warn_on_root = 1
