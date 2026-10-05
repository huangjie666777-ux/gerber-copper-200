# Gerber 铜层重建服务

接收单层 ASCII Gerber 光绘文件, 重建实际铜层轮廓, 输出面积/包围盒/连通块/孔洞统计, 并从同一最终几何生成 SVG 下载。纯后端, 无前端页面。

## 模块分工

- `gerber/parser.py` — 词法/语法解析, 输出事件流(含原文行号定位)
- `gerber/geometry.py` — 曝光几何引擎: 圆弧离散、光圈缓冲、区域填充、LPD/LPC 按序合成(Shapely)
- `gerber/svg_export.py` — 最终几何 → SVG(Y 轴翻转、evenodd 孔洞)
- `main.py` — FastAPI 请求处理: 上传、参数校验、错误响应、结果暂存

## 支持的 Gerber 子集

- `%FSLAXnnYnn*%` 前导零省略 + 绝对坐标; `%MOMM*%` / `%MOIN*%`
- `%ADDnnC,d*%` 圆形、 `%ADDnnR,xXy*%` 轴对齐矩形(仅闪光), 均无孔
- `Dnn` 选光圈; `D01` 绘制 / `D02` 移动 / `D03` 闪光; X/Y 省略沿用当前位置
- `G01` 直线; `G75` 下 `G02`/`G03` 顺/逆圆弧(跨象限、整圆, I/J 为相对起点的圆心偏移)
- `G36`/`G37` 单个简单直线闭环区域, 按内部填充
- `%LPD*%` 加铜 / `%LPC*%` 扣除, 严格按指令顺序组合, 后续 LPD 可恢复先前清除
- `G04` 注释、 `M02` 结束(缺失视为截断)

未定义光圈、非法圆弧、未闭合/自交区域、未支持指令、截断文件均返回 HTTP 422 及带行号与原文的错误, 不交付部分结果。

## 运行

```bash
.venv/bin/pip install -r requirements.txt   # 环境已备好可跳过
.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

## API

### POST /api/rebuild

multipart 上传: `file` = Gerber 文件; `tolerance` = 曲线近似误差(mm, 正数, 默认 0.01)。

```bash
curl -s -F "file=@samples/sample1.gbr" -F "tolerance=0.01" http://127.0.0.1:8000/api/rebuild
```

返回示例:

```json
{
  "area_mm2": 1234.567,
  "bbox_mm": {"min_x": 0, "min_y": 0, "max_x": 30, "max_y": 20, "width": 30, "height": 20},
  "components": 1,
  "holes": 1,
  "svg_id": "...",
  "svg_url": "/api/rebuild/<svg_id>/svg"
}
```

空铜层正常返回(area 为 0, bbox 为 null)。错误返回 422:

```json
{"detail": {"error": "未定义的光圈 D10", "line": 7, "source": "D10"}}
```

### GET /api/rebuild/{svg_id}/svg

下载由同一最终几何生成的 SVG(附件形式, 孔洞以 evenodd 正确表达, Y 轴方向已翻转)。

```bash
curl -OJ http://127.0.0.1:8000/api/rebuild/<svg_id>/svg
```

## 自测

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m compileall -q gerber main.py tests
```

样例见 `samples/`: `sample1.gbr`(区域+闪光+走线+圆弧+LPC 开孔后恢复)、`sample2.gbr`(英寸单位+整圆+顺时针圆弧)。
