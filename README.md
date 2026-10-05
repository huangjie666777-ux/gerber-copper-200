# Gerber 铜层重建后端

接收单层 ASCII Gerber 光绘文件，重建实际铜层轮廓，输出统计信息与 SVG 下载。纯后端，无前端页面。

## 模块分工

- `gerber_parser.py` — 词法/语法解析：FS/MO/AD/LP/G 码/D 码/坐标块，产出操作序列，所有错误带行号与原文。
- `geometry.py` — 曝光几何：光圈闪光/线/圆弧按宽度缓冲，G36/G37 区域填充，LPD 并集 / LPC 差集按指令顺序组合（Shapely）。
- `svg_export.py` — 由最终几何生成 SVG（`fill-rule="evenodd"` 显示孔洞，Y 轴翻转为 Gerber 的 Y 向上）。
- `app.py` — FastAPI 请求处理：上传、参数校验、任务存储、SVG 下载。

## 支持的 Gerber 子集

- `%FSLAXnnYnn*%`（绝对坐标、前导零省略，X/Y 格式一致）
- `%MOMM*%` / `%MOIN*%`
- `%ADDnnC,d*%`、`%ADDnnR,wXh*%`（无孔；R 仅可闪光 D03）
- `Dnn` 选光圈，`D01` 绘制、`D02` 移动、`D03` 闪光，省略的 X/Y 沿用当前位置
- `G01` 直线；`G75` 下 `G02`/`G03` 圆弧（I/J 为相对起点的圆心偏移，支持跨象限与整圆）
- `G36`/`G37` 单个简单直线闭环区域，按内部填充
- `%LPD*%` 加铜、`%LPC*%` 扣铜，按顺序组合，后续 LPD 可恢复先前清除部分
- `G04` 注释、`M02` 结束

未定义光圈、非法圆弧、未闭合/自交区域、未支持指令、截断文件均返回 422，携带 `error`、`line`、`text`，不交付部分结果。

## 运行

```bash
.venv/bin/uvicorn app:app --port 8000
```

## API

### POST /api/rebuild

multipart 表单：

- `file` — Gerber 文件（ASCII）
- `tolerance` — 可选，曲线近似误差（毫米，正数，默认 0.01）

返回：

```json
{
  "job_id": "…",
  "filename": "demo_mm.gbr",
  "tolerance_mm": 0.01,
  "area_mm2": 123.45,
  "bbox_mm": [0, 0, 10, 5],
  "components": 3,
  "holes": 1,
  "svg_url": "/api/rebuild/<job_id>/svg"
}
```

空铜层返回 `area_mm2=0`、`bbox_mm=null`、`components=0`、`holes=0`。

### GET /api/rebuild/{job_id}/svg

下载由同一最终几何生成的 SVG 文件。

## 示例

```bash
curl -F "file=@examples/demo_mm.gbr" -F "tolerance=0.01" http://127.0.0.1:8000/api/rebuild
curl -OJ http://127.0.0.1:8000/api/rebuild/<job_id>/svg
```

## 测试

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q gerber_parser.py geometry.py svg_export.py app.py tests
```
