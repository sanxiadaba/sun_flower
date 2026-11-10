"""用正多边形生成太阳花图案，输出 SVG 和 PNG。"""

from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

MIN_SIDES = 3
MAX_SIDES = 360
DEFAULT_LINE_WIDTH = 3.0
DEFAULT_RADIUS = 150.0
DEFAULT_MARGIN = 24.0
DEFAULT_SCALE = 2.0
DEFAULT_OUTPUT = Path("output/sun_flower")
BLACK = "#000000"
WHITE = "#ffffff"
MAX_PNG_DIMENSION = 8192
MAX_SUPERSAMPLED_PIXELS = 100_000_000
SUPERSAMPLE_TARGET_PIXELS = 24_000_000
MAX_ANTIALIAS = 4
MIN_RENDER_SIZE = 1e-6

Point = tuple[float, float]
Segment = tuple[Point, Point]


class FlowerError(Exception):
    """可以直接展示给用户的错误。"""


class ConfigurationError(FlowerError):
    """绘图参数不合法。"""


class RenderingError(FlowerError):
    """图像无法安全渲染。"""


@dataclass(frozen=True)
class FlowerConfig:
    sides: int
    line_width: float = DEFAULT_LINE_WIDTH
    tip_angle_degrees: float | None = None
    radius: float = DEFAULT_RADIUS
    margin: float = DEFAULT_MARGIN

    def __post_init__(self) -> None:
        if isinstance(self.sides, bool) or not isinstance(self.sides, int):
            raise ConfigurationError("边数必须是整数")
        if not MIN_SIDES <= self.sides <= MAX_SIDES:
            raise ConfigurationError(f"边数必须在 {MIN_SIDES} 到 {MAX_SIDES} 之间")
        _require_finite_positive("线宽", self.line_width)
        _require_finite_positive("半径", self.radius)
        _require_finite_non_negative("边距", self.margin)

        tip_angle = self.resolved_tip_angle_degrees
        if (
            not isinstance(tip_angle, (int, float))
            or isinstance(tip_angle, bool)
            or not math.isfinite(tip_angle)
            or not 0 < tip_angle < 180
        ):
            raise ConfigurationError("花瓣尖角必须大于 0 度且小于 180 度")

    @property
    def resolved_tip_angle_degrees(self) -> float:
        if self.tip_angle_degrees is None:
            return 360.0 / self.sides
        return self.tip_angle_degrees


@dataclass(frozen=True)
class FlowerGeometry:
    config: FlowerConfig
    inner_points: tuple[Point, ...]
    outer_points: tuple[Point, ...]
    outer_radius: float

    @property
    def segments(self) -> tuple[Segment, ...]:
        center = (0.0, 0.0)
        segments: list[Segment] = []
        for index, inner_point in enumerate(self.inner_points):
            next_inner = self.inner_points[(index + 1) % self.config.sides]
            outer_point = self.outer_points[index]
            segments.extend(
                (
                    (center, inner_point),
                    (inner_point, next_inner),
                    (inner_point, outer_point),
                    (outer_point, next_inner),
                )
            )
        return tuple(segments)


def _require_finite_positive(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{name}必须是数字")
    if not math.isfinite(value) or value <= 0:
        raise ConfigurationError(f"{name}必须是有限的正数")


def _require_finite_non_negative(name: str, value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigurationError(f"{name}必须是数字")
    if not math.isfinite(value) or value < 0:
        raise ConfigurationError(f"{name}必须是有限的非负数")


def calculate_geometry(config: FlowerConfig) -> FlowerGeometry:
    step = math.tau / config.sides
    half_tip = math.radians(config.resolved_tip_angle_degrees) / 2.0
    half_tip_tangent = math.tan(half_tip)
    if not math.isfinite(half_tip_tangent) or half_tip_tangent <= 0:
        raise ConfigurationError("花瓣尖角过小，无法进行稳定计算")

    side_length = 2.0 * config.radius * math.sin(step / 2.0)
    apothem = config.radius * math.cos(step / 2.0)
    outer_radius = apothem + (side_length / 2.0) / half_tip_tangent
    if not math.isfinite(outer_radius) or outer_radius <= 0:
        raise ConfigurationError("当前参数无法生成有效的花瓣尖点")

    inner_points = tuple(
        _polar_point(config.radius, index * step) for index in range(config.sides)
    )
    outer_points = tuple(
        _polar_point(outer_radius, step / 2.0 + index * step)
        for index in range(config.sides)
    )
    return FlowerGeometry(config, inner_points, outer_points, outer_radius)


def _polar_point(radius: float, angle: float) -> Point:
    return radius * math.cos(angle), radius * math.sin(angle)


def geometry_bounds(geometry: FlowerGeometry) -> tuple[float, float, float, float]:
    points = ((0.0, 0.0), *geometry.inner_points, *geometry.outer_points)
    padding = geometry.config.margin + geometry.config.line_width / 2.0
    left = min(point[0] for point in points) - padding
    bottom = min(point[1] for point in points) - padding
    right = max(point[0] for point in points) + padding
    top = max(point[1] for point in points) + padding
    if not all(math.isfinite(value) for value in (left, bottom, right, top)):
        raise RenderingError("图像边界过大，无法进行稳定渲染")
    if right - left < MIN_RENDER_SIZE or top - bottom < MIN_RENDER_SIZE:
        raise RenderingError(
            f"图形过小（{right - left:.3g} x {top - bottom:.3g}），请增大半径或边距"
        )
    return left, bottom, right, top


def render_svg(geometry: FlowerGeometry, output_path: Path) -> Path:
    left, bottom, right, top = geometry_bounds(geometry)
    width = right - left
    height = top - bottom
    view_top = -top
    snap = max(width, height) * 1e-12

    def number(value: float) -> str:
        return _number(value, zero=snap)

    title = (
        f"{geometry.config.sides} 边形太阳花，"
        f"花瓣尖角 {_number(geometry.config.resolved_tip_angle_degrees)}°"
    )
    path_data = " ".join(
        f"M {number(start[0])} {number(-start[1])} L {number(end[0])} {number(-end[1])}"
        for start, end in geometry.segments
    )
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{number(width)}" height="{number(height)}" '
        f'viewBox="{number(left)} {number(view_top)} '
        f'{number(width)} {number(height)}" role="img" '
        f'aria-label="{title}">\n'
        f"  <title>{title}</title>\n"
        f'  <rect x="{number(left)}" y="{number(view_top)}" '
        f'width="{number(width)}" height="{number(height)}" fill="{WHITE}"/>\n'
        f'  <path d="{path_data}" fill="none" stroke="{BLACK}" '
        f'stroke-width="{_number(geometry.config.line_width)}" '
        'stroke-linecap="round" stroke-linejoin="round"/>\n'
        "</svg>\n"
    )
    output_path = output_path.with_suffix(".svg")
    _atomic_write_text(output_path, svg)
    return output_path


def render_png(
    geometry: FlowerGeometry,
    output_path: Path,
    *,
    scale: float = DEFAULT_SCALE,
) -> Path:
    _require_finite_positive("PNG 缩放比例", scale)
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RenderingError(
            "生成 PNG 需要 Pillow，请先运行: python -m pip install -r requirements.txt"
        ) from exc

    left, bottom, right, top = geometry_bounds(geometry)
    base_width = right - left
    base_height = top - bottom
    scaled_width = base_width * scale
    scaled_height = base_height * scale
    if (
        not math.isfinite(scaled_width)
        or not math.isfinite(scaled_height)
        or scaled_width > MAX_PNG_DIMENSION
        or scaled_height > MAX_PNG_DIMENSION
    ):
        raise RenderingError("PNG 尺寸超过上限，请降低半径或 --scale")
    width = max(1, math.ceil(scaled_width))
    height = max(1, math.ceil(scaled_height))
    factor = _resolve_antialias(width, height)
    render_width = width * factor
    render_height = height * factor
    if render_width * render_height > MAX_SUPERSAMPLED_PIXELS:
        raise RenderingError(
            f"抗锯齿画布 {render_width}x{render_height} 过大，请降低半径或 --scale"
        )

    render_scale = scale * factor
    image = Image.new("RGB", (render_width, render_height), WHITE)
    draw = ImageDraw.Draw(image)
    stroke_width = max(1, round(geometry.config.line_width * render_scale))
    point_radius = stroke_width / 2.0

    def to_pixel(point: Point) -> Point:
        return (point[0] - left) * render_scale, (top - point[1]) * render_scale

    endpoints: set[Point] = set()
    for start, end in geometry.segments:
        start_pixel = to_pixel(start)
        end_pixel = to_pixel(end)
        draw.line((start_pixel, end_pixel), fill=BLACK, width=stroke_width)
        endpoints.update((start_pixel, end_pixel))

    for x, y in endpoints:
        draw.ellipse(
            (x - point_radius, y - point_radius, x + point_radius, y + point_radius),
            fill=BLACK,
        )

    if factor > 1:
        image = image.resize((width, height), Image.Resampling.LANCZOS)

    output_path = output_path.with_suffix(".png")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f".{output_path.name}.tmp")
    try:
        image.save(temporary_path, format="PNG", optimize=True)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output_path


def generate_files(
    config: FlowerConfig,
    output_base: Path,
    output_format: str = "both",
    *,
    scale: float = DEFAULT_SCALE,
) -> tuple[Path, ...]:
    if not isinstance(output_format, str) or output_format not in {
        "svg",
        "png",
        "both",
    }:
        raise ConfigurationError(f"不支持的输出格式: {output_format}")
    wants_png = output_format in {"png", "both"}
    wants_svg = output_format in {"svg", "both"}
    if wants_png:
        _require_finite_positive("PNG 缩放比例", scale)

    geometry = calculate_geometry(config)
    output_base = _without_image_suffix(output_base.expanduser())
    if output_base.is_dir():
        raise ConfigurationError(
            f"输出路径 {output_base} 是一个目录，请给出文件基础路径，例如 output/sun_flower"
        )

    generated: list[Path] = []
    if wants_png:
        generated.append(render_png(geometry, output_base, scale=scale))
    if wants_svg:
        generated.append(render_svg(geometry, output_base))
    return tuple(generated)


def _without_image_suffix(path: Path) -> Path:
    if path.suffix.lower() in {".png", ".svg"}:
        return path.with_suffix("")
    return path


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp")
    try:
        temporary_path.write_text(content, encoding="utf-8", newline="\n")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _number(value: float, *, zero: float = 0.0) -> str:
    if abs(value) <= zero:
        return "0"
    return f"{value:.9g}"


def _resolve_antialias(width: int, height: int) -> int:
    pixels = max(1, width * height)
    factor = math.isqrt(SUPERSAMPLE_TARGET_PIXELS // pixels)
    factor = max(1, min(MAX_ANTIALIAS, factor))
    if factor < 2 and pixels * 4 <= MAX_SUPERSAMPLED_PIXELS:
        factor = 2
    return factor


def _ensure_utf8_output() -> None:
    """控制台保持原生编码，重定向或管道时写 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or stream.isatty():
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成正多边形太阳花图案（SVG/PNG）")
    parser.add_argument(
        "-n",
        "--sides",
        type=int,
        required=True,
        metavar="N",
        help=f"正多边形边数（{MIN_SIDES}-{MAX_SIDES}）",
    )
    parser.add_argument(
        "-a", "--tip-angle", type=float, help="花瓣尖角（度），默认 360/边数"
    )
    parser.add_argument(
        "-w",
        "--line-width",
        type=float,
        default=DEFAULT_LINE_WIDTH,
        help="线宽，默认 3",
    )
    parser.add_argument(
        "--radius", type=float, default=DEFAULT_RADIUS, help="外接圆半径，默认 150"
    )
    parser.add_argument(
        "--margin", type=float, default=DEFAULT_MARGIN, help="图像边距，默认 24"
    )
    parser.add_argument(
        "--scale", type=float, default=DEFAULT_SCALE, help="PNG 缩放比例，默认 2"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("svg", "png", "both"),
        default="both",
        help="输出格式，默认同时生成 SVG 和 PNG",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="输出文件基础路径，默认 output/sun_flower",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _ensure_utf8_output()
    args = build_parser().parse_args(argv)
    try:
        config = FlowerConfig(
            sides=args.sides,
            line_width=args.line_width,
            tip_angle_degrees=args.tip_angle,
            radius=args.radius,
            margin=args.margin,
        )
        generated = generate_files(config, args.output, args.format, scale=args.scale)
    except (FlowerError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        return 130

    print("生成完成: " + ", ".join(str(path.resolve()) for path in generated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
