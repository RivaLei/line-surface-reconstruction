# 自定义 OBJ + LIMAP 重建

在项目根目录运行（入口会选择含 NumPy 的 Python）：

```bash
./scripts/custom_demo \
  --obj /path/to/clipped.obj \
  --limap-dir /path/to/limap/output \
  --name sztu12 --prepare-only

# 检查生成的 OBJ 后，复用最终 JSON 执行重建
./scripts/custom_demo --name sztu12
```

去掉 `--prepare-only` 可一次完成准备和重建。显式提供 `--limap-dir` 时默认重新生成，避免复用旧版仅添加相机中心的 JSON；`--reuse-final` 可显式优先复用完整最终输入。`--limap-output` 和 `--limap_dir` 为兼容别名。

输入 LIMAP 输出目录必须含 `finaltracks/track_*.txt`（含逐观测二维端点）以及 `finaltracks/imagecols.npy` 或根目录的 `imagecols.npy`。仅有 `alltracks.txt` 不够。相机须为去畸变后的 PINHOLE / SIMPLE_PINHOLE，二维端点须对应相同影像尺寸和相机内参；读取本地可信 NumPy 文件需要 NumPy，不需要安装 LIMAP Python 扩展。

处理顺序：

1. 读取 OBJ 的 `v/l`，按几何匹配完整 track。优先端点正反序精确匹配；否则要求两个裁剪端点均位于 track 线段内、到支撑线距离不超过 `--match-tolerance`（默认 `1e-6`，使用三维坐标单位）。多义或无匹配时报错，不猜测关联。整体坐标变换或重新拟合偏离支撑线的 OBJ 不适用。
2. 按 `(image_id, line_id)` 遍历所有二维观测，包括同一图像的多条观测。计算相机中心 `C = -R.T @ t`，将二维端点射线与三维支撑线作最近点求解，得到逐观测三维线段。与裁剪 OBJ 的区间取交集，再沿用官方端点各收缩 2.5% 的处理。退化、相机后方和无交集观测计数并排除；某个 OBJ 线段没有任何有效观测时报错。
3. 保存逐观测 `input_lines.json`，调用原有 `ransac_on_lines` 拟合平面，保存 `input_planes.json`。拟合对象为展开后的观测线段，因此与在原 track 上拟合再展开的平面结果可能不同。
4. 校验后输出 `input_lines_from_residuals.json` 和完全对应的 `input_lines_from_residuals.obj`，每条最终线仅含当前观测的一个 `pt_views`。保留 `obj_segment_id`、`limap_track_id`、`image_ids`、`line_id`、`line2d` 供追溯；track ID 来源为 `finaltracks/track_<ID>.txt`，不混用 `alltracks.txt` 的编号。顶层 `preparation` 记录方法及排除计数。
5. 默认继续调用 `line_based_recons`，`--prepare-only` 在准备后退出。

数据均位于 `data/<name>/`，结果沿用 `result/demo-<name>/` 和程序已有的检查点机制。默认使用 sztu12；prepare/all 会覆盖该名称下的生成数据，可通过 --name 指定其他实验目录。

RANSAC 默认 `--epsilon 0.02 --iterations 1000 --max-planes 30 --seed 0`。重建默认 `--cp 1 --cv 1 --ca 0 --ce 0.1 --cc 0.1 --scene ext`，可按场景调整。MOSEK 环境沿用之前设置。

未提供 LIMAP 时保留旧行为：完整最终 JSON 可直接复用；缺失时仅从 OBJ 准备几何和平面，缺少视点便停止。旧 `--viewpoint` 为全部线段共享相机中心的手工模式，不执行逐观测端点反投影。

## sztu12 已验证情况

输入 OBJ：`/home/lz/dataL/sztu12/sztu12/triangulated_lines_nv4_clipped.obj`。
LIMAP 目录：`/home/lz/project/limap-old/outputs/sztu12`。

1207 条输入 OBJ 线段均唯一匹配到 track，展开得到 22543 条逐观测三维线段，排除 12 个退化或裁剪后无交集的观测。以默认 RANSAC 参数检测到 29 个平面。已逐项核对最终 JSON 与 OBJ 的坐标和索引，6 项测试通过。验证产物位于 `/tmp`，原有 sztu12 数据和结果未覆盖；尚未运行本版输入的完整曲面重建，未评估网格质量。

## 命令入口 custom.sh

`custom.sh` 与本文均位于 `scripts/`，可从任意工作目录调用。默认使用上述实际输入路径，实验名称为 `sztu12`。

```bash
# 仅准备 JSON 和检查用 OBJ
./scripts/custom.sh prepare

# 查看 data/sztu12/input_lines_from_residuals.obj 后重建
./scripts/custom.sh reconstruct

# 一次完成准备及重建（默认模式；也可直接运行 ./scripts/custom.sh）
./scripts/custom.sh all

# 自定义输入和数据集名称
./scripts/custom.sh prepare \
  --obj /path/to/clipped.obj \
  --limap-dir /path/to/limap/output \
  --name another-dataset
./scripts/custom.sh reconstruct --name another-dataset
```

也可通过环境变量 `OBJ`、`LIMAP_DIR`、`NAME` 覆盖默认值，通过 `PYTHON` 指定解释器。模式后面的参数直接传给 `custom_demo`，可用于调整平面拟合和重建参数。`prepare`/`all` 每次重新读取 LIMAP 并生成输入；`reconstruct` 使用已有最终 JSON。若最终 JSON 缺失或不完整，底层入口仍遵循上文的旧版回退规则。


## 平面与线云可视化输出

`test_demo.py` 和 `custom_demo.py` 均默认启用 `-sa`。正常重建在完成平面划分后、权重计算前，将 `arrangement.ply` 写入各自的 `result/demo-<名称>/`。它包含有界平面划分面片，是诊断几何，不是最终重建表面。缓存恢复仍会执行该可视化导出。

两个入口还会在启动 C++ 重建前导出：

- `lines_by_plane.obj` + `lines_by_plane.mtl`：按 plane_index 着色的线云，打开 OBJ 时需保留同目录 MTL。
- `lines_by_plane.ply`：带 RGB 顶点和 edge 元素的线云，查看器需支持 PLY edge。
- `lines_by_plane.json`：平面编号、RGB、关联线数、平面参数及输入/显示线段数量的图例。

同一平面使用稳定颜色，未关联平面使用灰色。双平面线段仅在可视化中于中点拆成两半，分别使用较小/较大平面索引的颜色，所以显示线段数量可能多于输入；重建 JSON 和原有检查 OBJ 不变。

`custom_demo.py --prepare-only` 也会导出上述着色线云，但不启动重建，因此不会生成 arrangement.ply。需要平面划分时，运行 `./scripts/custom.sh reconstruct` 或 `./scripts/custom.sh all`；官方示例运行 `python3 scripts/test_demo.py`。

不传模式时，`./scripts/custom.sh` 默认执行 `all`：重新准备 LIMAP 逐观测输入、输出着色线云，并继续重建和导出 `arrangement.ply`。

## 包围盒来源

`--bbox-source camera|line` 默认为 `camera`，包围盒包含线段端点和相机中心。
`line` 仅用线段端点确定包围盒，相机观测仍保留用于可见性计算。两种模式均沿用 10% 包围盒扩展。

```bash
NAME=sztu12 BBOX_SOURCE=camera bash scripts/custom.sh reconstruct
NAME=sztu12 BBOX_SOURCE=line bash scripts/custom.sh reconstruct
bash scripts/custom.sh reconstruct --name sztu12 --bbox-source line
```

默认输出为 `result/demo-sztu12/`；线云模式输出为 `result/demo-sztu12_line_box/`。
输入仍复用 `data/sztu12/`，无需重新准备数据。直接调用 C++ 程序时可使用
`--bbox-source line`（或 `-bs line`），输出位置仍由 `-o` 指定。
