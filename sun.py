import turtle
from math import cos, pi, sin, tan

# 定义正多边形的边数和长度
num = int(input("输入正几边形: "))
try:
    my_size = int(input("输入线段粗细,默认是3: "))
except:
    my_size = 3

# 圆半径
r = 150

# 每个弧度
angle = (2 * pi / num)
ANGLE = angle

try:
    angle2 = float(input("输入外角度数，默认与内角相同: "))
    angle2 = (angle2 / 180) * pi
except:
    angle2 = angle
print("关闭任务栏后自动生成图片保存到本地")
turtle.setup(800, 800)
angles = []

for i in range(num):
    angles.append(angle * i)

points = []
for angle in angles:
    point = []
    point.append(r * cos(angle))
    point.append(r * sin(angle))
    points.append(point)

# 创建画布和画笔
pen = turtle.Turtle()
pen.hideturtle()
# 设置画笔速度和粗细
pen.speed(0)

pen.pensize(my_size)

angle = ANGLE

# 将画笔移动到第一个顶点
pen.penup()
pen.goto(0, 0)
pen.pendown()
for point in points:
    pen.goto(point[0], point[1])
    pen.goto(0, 0)

pen.goto(points[0][0], points[0][1])

for i in range(1, num):
    pen.goto(points[i][0], points[i][1])

pen.goto(points[0][0], points[0][1])

# 正多边形边长
r_sin = abs(r * sin(angle / 2) * 2)
# 正多边形边到中心距离
r_cos = abs(r * cos(angle / 2))

# 大圆边长
r2 = r_cos + abs((r_sin / 2) / tan(angle2 / 2))

angles2 = []
for i in range(num):
    angles2.append(angle / 2 + i * angle)

points2 = []
for angle2 in angles2:
    point2 = []
    point2.append(r2 * cos(angle2))
    point2.append(r2 * sin(angle2))
    points2.append(point2)

pen.goto(0, 0)

for i in range(num):
    pen.goto(points[i][0], points[i][1])
    pen.goto(points2[i][0], points2[i][1])

pen.goto(points[0][0], 0)

# 关闭画布
# turtle.done()

tsimg = pen.getscreen()
tsimg.getcanvas().postscript(file="work.eps")
# turtle.done()
turtle.bye()
import subprocess

subprocess.Popen(
    "gswin64c -dBATCH -dNOPAUSE -dEPSCrop -r300 -sDEVICE=png256 -sOutputFile=work.png work.eps",
    shell=False)

a = input(
    "=======================绘画完成，按任意键关闭程序==========================================="
)
print("\n")
# nuitka --standalone --show-memory --show-progress --nofollow-imports --plugin-enable=qt-plugins --follow-import-to=utils,src --output-dir=out --windows-icon-from-ico=./logo.ico demo.py
