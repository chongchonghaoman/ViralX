#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')
import subprocess
import webbrowser
import time

print("[启动] TikTok 分析工具 Web 应用...")
print("[地址] http://localhost:5000")
print("[提示] 按 Ctrl+C 停止服务器\n")

proc = subprocess.Popen([sys.executable, "web_app.py"])

try:
    time.sleep(2)
    webbrowser.open("http://localhost:5000")
    proc.wait()
except KeyboardInterrupt:
    print("\n[停止] 关闭服务器...")
    proc.terminate()
    proc.wait()
