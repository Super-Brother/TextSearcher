#!/usr/bin/env python3
"""Convert icon.png to icon.ico for Windows packaging.
Windows requires ICO with specific sizes for proper display.
"""

from PIL import Image
import os

# 检查 icon.png 是否存在
if not os.path.exists('icon.png'):
    print("Error: icon.png not found!")
    exit(1)

img = Image.open('icon.png')

# Windows 需要这些尺寸
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

print("Creating icon.ico with sizes:", sizes)

# 使用 PIL 的 ICO 保存功能
img.save(
    'icon.ico',
    format='ICO',
    sizes=sizes
)

print("✓ icon.ico created successfully with", len(sizes), "sizes")
