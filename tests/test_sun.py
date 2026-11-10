from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sun import (
    ConfigurationError,
    FlowerConfig,
    RenderingError,
    _resolve_antialias,
    calculate_geometry,
    generate_files,
    geometry_bounds,
    render_png,
    render_svg,
)

SVG_NS = "{http://www.w3.org/2000/svg}"


def run_cli(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(PROJECT_ROOT / "sun.py"), *arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


class GeometryTests(unittest.TestCase):
    def test_default_flower(self) -> None:
        geometry = calculate_geometry(FlowerConfig(sides=8))

        self.assertEqual(geometry.config.resolved_tip_angle_degrees, 45.0)
        self.assertEqual(len(geometry.inner_points), 8)
        self.assertEqual(len(geometry.outer_points), 8)
        self.assertEqual(len(geometry.segments), 32)
        self.assertAlmostEqual(geometry.outer_radius, 300 * math.cos(math.pi / 8))
        self.assertAlmostEqual(geometry.inner_points[0][0], 150.0)
        self.assertAlmostEqual(geometry.inner_points[0][1], 0.0)

    def test_sides_limits(self) -> None:
        for sides in (3, 360):
            with self.subTest(sides=sides):
                geometry = calculate_geometry(FlowerConfig(sides=sides))
                self.assertEqual(len(geometry.segments), sides * 4)
                self.assertTrue(math.isfinite(geometry.outer_radius))
        self.assertAlmostEqual(
            calculate_geometry(FlowerConfig(sides=3)).outer_radius, 150.0
        )

    def test_rejects_invalid_parameters(self) -> None:
        cases = (
            {"sides": 2},
            {"sides": 361},
            {"sides": 8, "line_width": 0},
            {"sides": 8, "line_width": math.inf},
            {"sides": 8, "tip_angle_degrees": 0},
            {"sides": 8, "tip_angle_degrees": 180},
            {"sides": 8, "tip_angle_degrees": "45"},
            {"sides": 8, "radius": -1},
            {"sides": 8, "margin": -1},
        )
        for values in cases:
            with self.subTest(values=values), self.assertRaises(ConfigurationError):
                FlowerConfig(**values)

    def test_tiny_tip_angle_is_rejected_at_render_time(self) -> None:
        config = FlowerConfig(sides=8, tip_angle_degrees=5e-324)
        with self.assertRaisesRegex(ConfigurationError, "尖角过小"):
            calculate_geometry(config)


class BoundsTests(unittest.TestCase):
    def test_bounds_include_margin_and_half_stroke(self) -> None:
        geometry = calculate_geometry(FlowerConfig(sides=4, margin=10, line_width=4))
        left, bottom, right, top = geometry_bounds(geometry)
        xs = [point[0] for point in geometry.outer_points]
        ys = [point[1] for point in geometry.outer_points]

        self.assertAlmostEqual(left, min(xs) - 12.0)
        self.assertAlmostEqual(right, max(xs) + 12.0)
        self.assertAlmostEqual(bottom, min(ys) - 12.0)
        self.assertAlmostEqual(top, max(ys) + 12.0)

    def test_tiny_geometry_is_rejected(self) -> None:
        geometry = calculate_geometry(
            FlowerConfig(sides=8, radius=1e-9, margin=0, line_width=1e-9)
        )
        with self.assertRaisesRegex(RenderingError, "图形过小"):
            geometry_bounds(geometry)


class SvgTests(unittest.TestCase):
    def test_default_layers_and_chinese_title(self) -> None:
        geometry = calculate_geometry(FlowerConfig(sides=8))
        with tempfile.TemporaryDirectory() as directory:
            output = render_svg(geometry, Path(directory) / "flower")
            text = output.read_text(encoding="utf-8")
        root = ET.fromstring(text)

        self.assertEqual(root.tag, SVG_NS + "svg")
        self.assertEqual(root.attrib["role"], "img")
        view_box = [float(value) for value in root.attrib["viewBox"].split()]
        self.assertEqual(len(view_box), 4)
        self.assertGreater(view_box[2], 0)
        self.assertGreater(view_box[3], 0)
        self.assertEqual(root.find(f"{SVG_NS}title").text, "8 边形太阳花，花瓣尖角 45°")
        self.assertEqual(text.count("<path "), 1)
        path_data = root.find(f"{SVG_NS}path").attrib["d"]
        self.assertNotIn("e", path_data)  # 坐标不该带浮点噪声或科学计数法
        self.assertIn('fill="#ffffff"', text)
        self.assertIn('stroke="#000000"', text)

    def test_tiny_geometry_keeps_precision(self) -> None:
        geometry = calculate_geometry(
            FlowerConfig(sides=8, radius=1e-4, margin=0, line_width=1e-4)
        )
        with tempfile.TemporaryDirectory() as directory:
            output = render_svg(geometry, Path(directory) / "tiny")
            text = output.read_text(encoding="utf-8")
        root = ET.fromstring(text)
        view_box = [float(value) for value in root.attrib["viewBox"].split()]

        self.assertTrue(all(value > 0 for value in view_box[2:]), view_box)
        self.assertIn("e-05", text)  # 坐标按有效数字输出，不会被截成 0


class PngTests(unittest.TestCase):
    def test_default_dimensions_and_white_background(self) -> None:
        from PIL import Image

        geometry = calculate_geometry(FlowerConfig(sides=8))
        with tempfile.TemporaryDirectory() as directory:
            output = render_png(geometry, Path(directory) / "flower", scale=1)
            with Image.open(output) as image:
                self.assertEqual(image.size, (564, 564))
                self.assertEqual(image.mode, "RGB")
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
                colors = image.getcolors(maxcolors=image.width * image.height)
                self.assertTrue(colors)
                self.assertTrue(all(r == g == b for _, (r, g, b) in colors))

    def test_oversized_png_is_rejected(self) -> None:
        geometry = calculate_geometry(
            FlowerConfig(sides=3, tip_angle_degrees=0.1, radius=1000)
        )
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaises(RenderingError),
        ):
            render_png(geometry, Path(directory) / "huge", scale=2)

    def test_auto_antialias_stays_within_budget(self) -> None:
        for size in (1127, 3000, 8000):
            with self.subTest(size=size):
                factor = _resolve_antialias(size, size)
                self.assertGreaterEqual(factor, 1)
                self.assertLessEqual(factor, 4)
                self.assertLessEqual((size * factor) ** 2, 100_000_000)


class OutputTests(unittest.TestCase):
    def test_suffix_and_directory_handling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_files(
                FlowerConfig(sides=6), Path(directory) / "flower.svg", "svg"
            )
            self.assertEqual(generated, (Path(directory) / "flower.svg",))
            self.assertTrue(generated[0].is_file())

            target = Path(directory) / "a_directory"
            target.mkdir()
            with self.assertRaisesRegex(ConfigurationError, "目录"):
                generate_files(FlowerConfig(sides=6), target, "svg")

    def test_svg_only_ignores_scale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            generated = generate_files(
                FlowerConfig(sides=6), Path(directory) / "flower", "svg", scale=0
            )
            self.assertEqual(len(generated), 1)


class CliTests(unittest.TestCase):
    def test_generates_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "flower"
            result = run_cli("-n", "8", "-o", str(output), cwd=Path(directory))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.with_suffix(".svg").is_file())
            self.assertTrue(output.with_suffix(".png").is_file())
            self.assertIn("生成完成", result.stdout)

    def test_invalid_sides_exits_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_cli("-n", "2", cwd=Path(directory))

        self.assertEqual(result.returncode, 2)
        self.assertIn("边数必须", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_svg_only_writes_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "flower"
            result = run_cli(
                "-n", "6", "-f", "svg", "-o", str(output), cwd=Path(directory)
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(output.with_suffix(".svg").is_file())
            self.assertFalse(output.with_suffix(".png").exists())


if __name__ == "__main__":
    unittest.main()
