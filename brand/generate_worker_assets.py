#!/usr/bin/env python3
"""
브랜드 원본(twin-fang-logo.jpg) > Worker 아이콘 PNG·ICO > control-tower-worker/src/brand_assets.js (base64)
macOS sips로 크기 변환(BMP) > 표준 라이브러리로 잡음 정리·PNG 인코딩, 원본을 바꾸면 이 스크립트를 다시 실행
실행: python3 brand/generate_worker_assets.py
"""
import base64
import pathlib
import struct
import subprocess
import sys
import tempfile
import zlib

BRAND_DIRECTORY = pathlib.Path(__file__).resolve().parent
SOURCE_LOGO_PATH = BRAND_DIRECTORY / "twin-fang-logo.jpg"
OUTPUT_MODULE_PATH = BRAND_DIRECTORY.parent / "control-tower-worker" / "src" / "brand_assets.js"

# 로고 바탕색 #151515 (og 여백·잡음 정리 기준)
BACKGROUND_RGB = (0x15, 0x15, 0x15)
# og 이미지: 캔버스 512 안에 로고 320 가운데
OG_CANVAS_PIXELS = 512
OG_LOGO_PIXELS = 320
# JPEG 잡음 제거: 바탕색과 채널 차이가 이 값 이하면 바탕색으로
BACKGROUND_SNAP_DISTANCE = 10
# 색 양자화 간격 (채널 값을 이 배수로 내림, 팔레트 256색 이하 > 인덱스 PNG)
COLOR_QUANTIZE_STEP = 12
MAXIMUM_PALETTE_COLORS = 256
# 생성 모듈 최대 크기 (base64 포함, 120KB)
MAXIMUM_MODULE_BYTES = 120 * 1024

# favicon.ico 두 번째 크기 (픽셀)
FAVICON_LARGE_PIXELS = 48
# 생성 PNG: (내보낼 이름, 한 변 픽셀)
SQUARE_ASSETS = [
    ("FAVICON_PNG", 32),
    ("APPLE_TOUCH_ICON_PNG", 180),
    ("LOGO_PNG", 128),
]


def run_sips(arguments):
    """sips 실행 (실패 시 표준 오류 출력 후 종료)"""
    completed = subprocess.run(["sips", *arguments], capture_output=True, text=True)
    if completed.returncode != 0:
        sys.exit(f"[brand assets] sips failed : {completed.stderr.strip()}")


def resize_square_png(size_pixels, working_directory):
    """원본 > 정사각 BMP(sips) > 잡음 정리·양자화 > PNG 바이트"""
    bitmap_path = working_directory / f"logo_{size_pixels}.bmp"
    run_sips(["-s", "format", "bmp", "-z", str(size_pixels), str(size_pixels), str(SOURCE_LOGO_PATH), "--out", str(bitmap_path)])
    width, height, pixels = read_bitmap(bitmap_path.read_bytes())
    return encode_png(width, height, [quantize_color(pixel) for pixel in pixels])


def read_bitmap(bitmap_bytes):
    """24비트 BMP > (너비, 높이, [(r, g, b)] 위 행부터)"""
    pixel_offset = struct.unpack_from("<I", bitmap_bytes, 10)[0]
    width, signed_height, _, bits_per_pixel = struct.unpack_from("<iiHH", bitmap_bytes, 18)
    if bits_per_pixel != 24:
        sys.exit(f"[brand assets] unsupported bmp : {bits_per_pixel} bits")
    height = abs(signed_height)
    row_bytes = (width * 3 + 3) // 4 * 4
    # 높이 양수 = 아래 행부터 저장
    row_order = range(height) if signed_height < 0 else range(height - 1, -1, -1)
    pixels = []
    for row_index in row_order:
        row_start = pixel_offset + row_index * row_bytes
        for column_index in range(width):
            blue, green, red = bitmap_bytes[row_start + column_index * 3: row_start + column_index * 3 + 3]
            pixels.append((red, green, blue))
    return width, height, pixels


def quantize_color(pixel):
    """바탕 근처 > 바탕색, 그 외 채널 COLOR_QUANTIZE_STEP 배수로 내림"""
    background = BACKGROUND_RGB
    if all(abs(channel - base) <= BACKGROUND_SNAP_DISTANCE for channel, base in zip(pixel, background)):
        return background
    return tuple(channel // COLOR_QUANTIZE_STEP * COLOR_QUANTIZE_STEP for channel in pixel)


def encode_png(width, height, pixels):
    """[(r, g, b)] > PNG (256색 이하 인덱스, 아니면 RGB 24비트)"""
    palette = sorted(set(pixels))
    is_indexed = len(palette) <= MAXIMUM_PALETTE_COLORS
    index_by_color = {color: index for index, color in enumerate(palette)}
    raw_rows = bytearray()
    for row_index in range(height):
        raw_rows.append(0)  # 필터 0 (없음)
        row_pixels = pixels[row_index * width:(row_index + 1) * width]
        if is_indexed:
            raw_rows.extend(index_by_color[color] for color in row_pixels)
        else:
            for color in row_pixels:
                raw_rows.extend(color)
    # 색 형식 3 인덱스 | 2 RGB
    header = struct.pack(">IIBBBBB", width, height, 8, 3 if is_indexed else 2, 0, 0, 0)
    chunks = [png_chunk(b"IHDR", header)]
    if is_indexed:
        chunks.append(png_chunk(b"PLTE", bytes(channel for color in palette for channel in color)))
    chunks.append(png_chunk(b"IDAT", zlib.compress(bytes(raw_rows), 9)))
    chunks.append(png_chunk(b"IEND", b""))
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def png_chunk(chunk_type, chunk_data):
    """PNG 청크: 길이 > 종류 > 데이터 > CRC(종류+데이터)"""
    return struct.pack(">I", len(chunk_data)) + chunk_type + chunk_data + struct.pack(">I", zlib.crc32(chunk_type + chunk_data))


def build_og_png(working_directory):
    """로고 OG_LOGO_PIXELS 양자화 > 512 캔버스 가운데 (여백 바탕색)"""
    bitmap_path = working_directory / "og.bmp"
    run_sips(["-s", "format", "bmp", "-z", str(OG_LOGO_PIXELS), str(OG_LOGO_PIXELS), str(SOURCE_LOGO_PATH), "--out", str(bitmap_path)])
    _, _, logo_pixels = read_bitmap(bitmap_path.read_bytes())
    margin_pixels = (OG_CANVAS_PIXELS - OG_LOGO_PIXELS) // 2
    canvas = [BACKGROUND_RGB] * (OG_CANVAS_PIXELS * OG_CANVAS_PIXELS)
    for logo_row in range(OG_LOGO_PIXELS):
        canvas_start = (logo_row + margin_pixels) * OG_CANVAS_PIXELS + margin_pixels
        logo_start = logo_row * OG_LOGO_PIXELS
        canvas[canvas_start:canvas_start + OG_LOGO_PIXELS] = [quantize_color(pixel) for pixel in logo_pixels[logo_start:logo_start + OG_LOGO_PIXELS]]
    return encode_png(OG_CANVAS_PIXELS, OG_CANVAS_PIXELS, canvas)


def wrap_pngs_as_ico(png_bytes_by_size):
    """PNG 여러 장 > ICO 컨테이너 (헤더 6B + 항목 16B씩 + PNG 그대로, Vista 이후 PNG 내장 ICO 지원)"""
    header = struct.pack("<HHH", 0, 1, len(png_bytes_by_size))
    entries = b""
    data_offset = 6 + 16 * len(png_bytes_by_size)
    for size_pixels, png_bytes in png_bytes_by_size:
        # 너비·높이 1바이트 (256이면 0), 색 수 0, 예약 0, 평면 1, 32비트, 데이터 크기, 데이터 시작 위치
        entries += struct.pack("<BBBBHHII", size_pixels % 256, size_pixels % 256, 0, 0, 1, 32, len(png_bytes), data_offset)
        data_offset += len(png_bytes)
    return header + entries + b"".join(png_bytes for _, png_bytes in png_bytes_by_size)


def to_module_source(asset_bytes_by_name):
    """자산 바이트 > ES 모듈 소스 (export const 이름 = 'base64')"""
    lines = [
        "/**",
        " * 생성 파일: brand/generate_worker_assets.py가 brand/twin-fang-logo.jpg에서 만듦 (직접 수정 금지)",
        " * 브랜드 아이콘 base64 (PNG, FAVICON_ICO는 PNG 32·48 내장 ICO)",
        " */",
    ]
    for name, asset_bytes in asset_bytes_by_name.items():
        lines.append(f"export const {name}_BASE64 = '{base64.b64encode(asset_bytes).decode('ascii')}';")
    return "\n".join(lines) + "\n"


def main():
    asset_bytes_by_name = {}
    with tempfile.TemporaryDirectory() as temporary_directory:
        working_directory = pathlib.Path(temporary_directory)
        for name, size_pixels in SQUARE_ASSETS:
            asset_bytes_by_name[name] = resize_square_png(size_pixels, working_directory)
        # ICO = 32·48 두 장, 48은 ICO 안에만 둠
        favicon_large_png = resize_square_png(FAVICON_LARGE_PIXELS, working_directory)
        asset_bytes_by_name["FAVICON_ICO"] = wrap_pngs_as_ico(
            [(32, asset_bytes_by_name["FAVICON_PNG"]), (FAVICON_LARGE_PIXELS, favicon_large_png)])
        asset_bytes_by_name["OG_PNG"] = build_og_png(working_directory)

    module_source = to_module_source(asset_bytes_by_name)
    if len(module_source.encode("utf-8")) > MAXIMUM_MODULE_BYTES:
        sys.exit(f"[brand assets] module too large : {len(module_source)} bytes > {MAXIMUM_MODULE_BYTES}")
    OUTPUT_MODULE_PATH.write_text(module_source, encoding="utf-8")
    for name, asset_bytes in asset_bytes_by_name.items():
        print(f"[brand assets] {name} : {len(asset_bytes)} bytes")
    print(f"[brand assets] wrote {OUTPUT_MODULE_PATH.name} : {len(module_source)} bytes")


if __name__ == "__main__":
    main()
