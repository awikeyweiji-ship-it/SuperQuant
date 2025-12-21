"""调整 sys.path 以优先使用系统依赖，避免本地 Windows 版包污染。"""
import sys

site_paths = [p for p in sys.path if "site-packages" in p]
other_paths = [p for p in sys.path if p not in site_paths and p != ""]
# 确保 site-packages 放在最前，当前目录放在最后
sys.path = site_paths + other_paths + [""]
