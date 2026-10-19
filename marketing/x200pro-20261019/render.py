import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1200, 1500
COLORS = {
    "base": "#111c27", "deep": "#08111b", "paper": "#eee6d3",
    "muted": "#a8bac5", "brass": "#c4a16b", "violet": "#b393e6",
}
FONT_ROOT = Path("C:/Windows/Fonts")


def font(size, display=False, strong=False):
    filename = "georgiab.ttf" if display else "msyhbd.ttc" if strong else "msyh.ttc"
    return ImageFont.truetype(str(FONT_ROOT / filename), size)


def text(draw, position, content, size, color="paper", display=False, strong=False):
    draw.text(position, content, font=font(size, display, strong), fill=COLORS.get(color, color), spacing=14)


def canvas(section):
    result = Image.new("RGB", (WIDTH, HEIGHT), COLORS["base"])
    draw = ImageDraw.Draw(result)
    draw.rectangle((0, 0, 18, HEIGHT), fill=COLORS["brass"])
    text(draw, (76, 58), "D3R Mobile", 34, strong=True)
    text(draw, (76, 111), "Android development journal", 20, "muted")
    text(draw, (842, 69), section, 22, "brass")
    draw.line((76, 160, 1124, 160), fill="#344655", width=2)
    text(draw, (76, 1395), "github.com/Ergouf/d3r-mobile", 23, "brass")
    text(draw, (76, 1440), "Unofficial project. Own game data required. Work in progress.", 17, "muted")
    return result, draw


def screenshot(canvas_image, source_name, top, width=1048, left=76):
    source = Image.open(ROOT / "screens" / source_name).convert("RGB")
    target_height = round(width * source.height / source.width)
    resized = source.resize((width, target_height), Image.Resampling.LANCZOS)
    canvas_image.paste(resized, (left, top))
    draw = ImageDraw.Draw(canvas_image)
    draw.rectangle((left - 1, top - 1, left + width, top + target_height), outline="#658091", width=1)
    return top + target_height


def save_poster(image, name):
    target = ROOT / "images" / name
    target.parent.mkdir(exist_ok=True)
    image.save(target, optimize=True)
    return target


def render():
    generated = []
    image, draw = canvas("Device diary")
    text(draw, (72, 205), "Sanctuary.\nIn your hands.", 90, display=True)
    text(draw, (76, 454), "把熟悉的世界，带到掌心。", 32)
    bottom = screenshot(image, "gameplay-clean.png", 546)
    text(draw, (76, bottom + 44), "Captured on vivo X200 Pro", 35, strong=True)
    text(draw, (76, bottom + 106), "Dimensity 9400  /  Mali-G925  /  Android 16", 24, "muted")
    text(draw, (76, bottom + 172), "真实设备截图。不是概念渲染，也不是云串流演示。", 24)
    text(draw, (76, bottom + 220), "An experimental Android compatibility-layer build.", 23, "muted")
    generated.append(save_poster(image, "01-in-your-hands.png"))

    image, draw = canvas("Native viewport")
    text(draw, (72, 205), "A wider world.\nNot a wider hero.", 78, display=True)
    text(draw, (76, 440), "扩展游戏视野，不把人物拉宽。", 31)
    bottom = screenshot(image, "gameplay-controls.png", 532)
    text(draw, (76, bottom + 38), "2000 × 900", 72, "paper", display=True)
    text(draw, (76, bottom + 137), "Native guest output matched to a 20:9 display.", 26, "muted")
    text(draw, (76, bottom + 208), "原生分辨率与画面比例同步；菜单边缘修复仍待最终复测。", 23)
    text(draw, (76, bottom + 256), "Widescreen remains an active compatibility test.", 23, "muted")
    generated.append(save_poster(image, "02-native-widescreen.png"))

    image, draw = canvas("Touch controls")
    text(draw, (72, 205), "Your thumb.\nYour starting point.", 75, display=True)
    text(draw, (76, 437), "安全区内落指，摇杆随手而生。", 30)
    first_bottom = screenshot(image, "floating-live-one.png", 505, width=848, left=176)
    text(draw, (176, first_bottom + 12), "Live overlay test over a cutscene / 过场触控层测试", 20, "muted")
    second_top = first_bottom + 60
    second_bottom = screenshot(image, "floating-live-two.png", second_top, width=848, left=176)
    text(draw, (176, second_bottom + 12), "A new touch. A new origin. Release returns to neutral.", 21, "muted")
    generated.append(save_poster(image, "03-floating-touch.png"))

    image, draw = canvas("Open development")
    text(draw, (72, 205), "Real hardware.\nVisible progress.", 82, display=True)
    text(draw, (76, 447), "看得见的画面，查得到的实现。", 30)
    bottom = screenshot(image, "menu-clean.png", 532)
    text(draw, (76, bottom + 35), "Vulkan on Mali-G925", 36, strong=True)
    text(draw, (76, bottom + 98), "Native viewport. Floating controls. Driver-load verification.", 22, "muted")
    text(draw, (76, bottom + 151), "不把标题帧率说成玩法性能，不把系统核心补全说成驱动升级。", 21)
    text(draw, (76, bottom + 208), "No stable-60fps or AI-frame-generation claim.", 25, "violet")
    text(draw, (76, bottom + 259), "Source and development notes are on GitHub.", 23, "muted")
    generated.append(save_poster(image, "04-built-in-the-open.png"))

    contact = Image.new("RGB", (1200, 1500), "#ffffff")
    for index, target in enumerate(generated):
        thumbnail = Image.open(target).resize((600, 750), Image.Resampling.LANCZOS)
        contact.paste(thumbnail, ((index % 2) * 600, (index // 2) * 750))
    contact.save(ROOT / "contact-sheet.jpg", quality=90)
    print(json.dumps([str(path) for path in generated], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render X promotional images from full, uncropped device screenshots.")
    parser.parse_args()
    render()
