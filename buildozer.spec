[app]
title = opentuna
package.name = opentuna
package.domain = com.kaykcaputo
source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,ttf,atlas,json
version = 1.0.0
android.numeric_version = 10000

requirements = python3,kivy,numpy,pyjnius

orientation = portrait
fullscreen = 0

android.permissions = RECORD_AUDIO,VIBRATE
android.api = 34
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
android.release_artifact = aab
android.enable_androidx = True
android.allow_backup = False
android.keystore = ./keystore/opentuna-release.keystore
android.keystore_passwd =
android.keyalias = opentuna
android.keyalias_passwd =

[buildozer]
log_level = 2
warn_on_root = 1