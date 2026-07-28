from io import BytesIO
from PIL import Image, ImageDraw


def generate_icon():
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bg_color = (24, 144, 255, 255)
    corner = size // 5
    draw.rounded_rectangle([0, 0, size, size], radius=corner, fill=bg_color)

    bar_color = (255, 255, 255, 255)
    center_x = size // 2
    bar_width = size // 8
    spacing = size // 6

    heights = [size * 0.35, size * 0.55, size * 0.35]
    xs = [center_x - spacing, center_x, center_x + spacing]
    for h, x in zip(heights, xs):
        top = (size - h) / 2
        draw.rounded_rectangle(
            [x - bar_width / 2, top, x + bar_width / 2, top + h],
            radius=bar_width / 2,
            fill=bar_color,
        )

    img.save('build/icon.png')

    # Save a single 256x256 ICO; electron-builder requires at least 256x256.
    # rcedit (used by electron-builder) does not accept the PNG-encoded
    # 256x256 frame that Pillow writes by default, so force a 32-bit BMP
    # encoded icon by saving through an in-memory BMP and repacking it.
    ico = img.resize((256, 256), Image.LANCZOS)
    bmp_buf = BytesIO()
    # BMP does not support alpha, so composite onto the brand blue background.
    bg = Image.new('RGB', (256, 256), (24, 144, 255))
    bg.paste(ico, mask=ico.split()[3])
    bg.save(bmp_buf, format='BMP')
    bmp_buf.seek(0)
    ico_bmp = Image.open(bmp_buf)
    ico_bmp.save('build/icon.ico', format='ICO', sizes=[(256, 256)])

    print('Generated build/icon.png and build/icon.ico (256x256)')


if __name__ == '__main__':
    generate_icon()
