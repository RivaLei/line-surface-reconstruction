# 官方示例与 VS Code 调试

以下命令从仓库根目录运行。`demo.sh` 中有五个示例，输入数据已经包含在 `data/` 中。
它们直接从检测好的线段和平面运行重建，不需要先执行从照片提取线段的流程。

## 终端运行一个官方示例

```bash
export MOSEK_DIR=/home/lz/project/third_/mosek
export MOSEKLM_LICENSE_FILE="$MOSEK_DIR/mosek.lic"
export LD_LIBRARY_PATH="$MOSEK_DIR/8/tools/platform/linux64x86/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

mkdir -p result/demo-Andalusian
./build/line_based_recons \
  -i data/Andalusian/input_lines_from_residuals.json \
  -o result/demo-Andalusian/ \
  -cp 1 -cv 1 -ca 0 -ce 0.1 -cc 0.1 -ext -v
```

这是 `demo.sh` 的 Andalusian 参数，输出目录为 `result/demo-Andalusian/`。
输出文件为 `cp_1_cv_1_ca_0_ce_0.1_cc_0.1.ply`，可用已有的 MeshLab 或 CloudCompare 打开。
目录必须事先创建。运行中的平面插入、权重计算和优化阶段可能需要等待。

执行 `bash demo.sh` 会依次运行全部五个示例，分别保存到
`result/demo-Andalusian/`、`result/demo-Barn/`、`result/demo-Bridge/`、
`result/demo-HouseInterior/` 和 `result/demo-TimberFrame/`。

## VS Code 调试

本机已有 Microsoft C/C++ 扩展和 `/usr/bin/gdb`。用 VS Code 打开本仓库根目录。

1. 打开 `main.cpp`，在第 77 行（读取输入）或第 85 行（创建平面排列）左侧点击添加断点。
2. 打开“运行和调试”（`Ctrl+Shift+D`），选择 **Demo: Andalusian (GDB)**。
3. 按 `F5`。任务会自动配置并编译 Debug 版本，创建输出目录，然后启动 GDB。
4. `F10` 单步跳过，`F11` 进入函数，`Shift+F11` 跳出，`F5` 继续，`Shift+F5` 停止。
5. 查看左侧“变量”和“监视”。例如在读取输入后查看 `myLineSet`、`myPrimitiveSet`。

五个场景都有独立调试配置，参数与 `demo.sh` 一致，结果分别写入
`result/demo-场景名/`。相关文件：`.vscode/launch.json` 与 `.vscode/tasks.json`。
调试配置显式设置许可证和 MOSEK 动态库路径，不依赖 VS Code 是否继承了终端环境。

Release 程序位于 `build/`，带调试符号的程序位于 `build-debug/`。
默认开启 OpenMP，可能出现多个线程。`libPlaneArr.a` 是项目自带的预编译库，
本次也未重新编译 CGAL 或 MOSEK 的 Debug 版本；不能保证能逐行进入这些外部库。

建议依次在以下位置观察：

| 位置 | 作用 |
| --- | --- |
| `main.cpp:77` | 加载输入线段与平面 |
| `main.cpp:85` | 构造平面排列 |
| `main.cpp:88` | 计算权重 |
| `main.cpp:97` | 调用 MOSEK 求解 |
| `main.cpp:106` | 保存 PLY |

若只想快速验证断点与流程，可以在调试配置的 `args` 中添加 `"-np", "10"`，
将输入平面限制为 10 个。这会改变重建结果，不等同于完整官方示例。

运行现有测试：

```bash
ctest --test-dir build --output-on-failure
```

该命令需要前面的 MOSEK 环境变量。已配置有效许可证时，现有 36 项测试全部通过。

## 可选的平面划分中间结果

给 `build/line_based_recons` 添加 `-sa`（或 `--save-arrangement`），会在平面划分及求交树构建完成后、线段权重计算前，调用 `saveArrangementAsPly()` 保存 `<输出目录>/arrangement.ply`，然后继续正常重建。

```bash
mkdir -p result/quick-Andalusian
OMP_NUM_THREADS=2 build/line_based_recons \
  -i data/Andalusian/input_lines_from_residuals.json \
  -o result/quick-Andalusian/ \
  -np 20 -cp 1 -cv 1 -ca 0 -ce 0.1 -cc 0.1 -ext -v -sa
```

命令需使用上文的 MOSEK 环境。VS Code 调试时，在对应配置的 `args` 中添加 `"-sa"` 即可；`demo.sh` 中也需在需要的命令上添加该参数才会导出。

日志会输出 `Saving intermediate plane arrangement: ...` 和 `Intermediate plane arrangement saved; starting weight computation.`，用于确认导出完成及进入下一阶段。
该 PLY 展示所有有界划分面，可用 MeshLab 等工具查看候选平面的空间划分；它不是优化后的重建表面，也不是可恢复计算的检查点。导出本身需要额外时间和内存，同一输出目录下的 `arrangement.ply` 会被覆盖。默认不导出；已运行的旧进程不会获得新增功能。

已用小规模输入验证：中间 PLY 在权重计算及求解前生成；不加参数时不生成；两种方式的最终重建 PLY 一致。

## 自动保存与恢复检查点

`line_based_recons` 默认启用检查点。中断后，在同一输出目录使用原命令重新运行即可自动加载，无需增加恢复参数；日志中的 `[resume]` 表示正在复用已有状态。检查点从本次新增功能后的首次运行开始保存，不能恢复此前旧进程未保存的状态。

检查点位于 `<输出目录>/checkpoints/<标识>/`：

| 文件 | 保存时机与恢复作用 |
| --- | --- |
| `manifest.json` | 输入内容、程序二进制及参数指纹，隔离不兼容的缓存 |
| `arrangement.geometry.json`、`arrangement.json` | 完成平面插入后，保存精确有理数坐标、完整拓扑及平面映射；恢复时跳过平面插入 |
| `weights.json` | 默认每处理完 100 条输入线段后保存累计 cell/facet 权重、结构代价和下一条线段位置 |
| `model.json` | 依次完成 boundary、structural、visibility/area、edge、corner 各项后，保存累计目标函数与稀疏约束；恢复后只计算未完成项 |
| `solution.json` | 求解成功后保存标签及 cell 映射；若在导出最终 PLY 前中断，可直接加载结果重新导出 |

示例：

```bash
mkdir -p result/quick-Andalusian
OMP_NUM_THREADS=2 build/line_based_recons \
  -i data/Andalusian/input_lines_from_residuals.json \
  -o result/quick-Andalusian/ \
  -np 20 -cp 1 -cv 1 -ca 0 -ce 0.1 -cc 0.1 -ext -v -sa -cb 100
# 中断后原样再执行上述命令，即可恢复。
```

`-cb` / `--checkpoint-batch` 设置权重保存批次大小（正整数）；调小可以减少中断后的重算量，但会更频繁地写盘。批次边界会等待该批所有线程完成，确保恢复时不重复计权。未归属平面或退化投影的线段也计入已扫描位置。

`-nc` / `--no-checkpoints` 关闭缓存读写，完全重新计算。批次大小与 `-sa` 不影响缓存身份；输入 JSON 内容、权重参数、场景类型、平面上限、体素大小或程序二进制变化会使用新标识。Release 与 Debug 使用不同缓存；重新编译后若二进制变化，也不复用旧缓存。同一标识的缓存目录有进程锁，防止两个进程同时覆盖。

写文件采用 `.tmp` 后原子替换，启动时忽略未完成的临时文件。检测到损坏的正式检查点会报错停止，不默默加载错误状态。

恢复边界：

- JSON 读取与平面定向会重新执行，求交 AABB 加速树也会根据已加载几何重新构建；树节点含进程内指针，不直接序列化。
- 平面插入尚未全部完成时中断，需要重做该阶段；权重阶段只重做最后未保存的批次，模型项生成只重做最后未保存的项。
- 已保存的是优化模型项，并非 MOSEK 内部求解器状态。恢复后仍会重新建立 Fusion 约束；如果求解尚未完成，需要重新求解；若已有 `solution.json` 则跳过求解。
- 缓存会额外占用磁盘，JSON 序列化/加载也需要时间与内存。没有缓存清理功能；原有 `arrangement.ply` 仍只是可视化文件，与可恢复检查点用途不同。

验证：Release 和 Debug 均进行过几何/结构代价恢复、实际中断批次后恢复、部分模型项恢复、完整求解结果复用以及输入/参数变化隔离测试。恢复后的累计权重与最终 PLY 均与无缓存计算一致。
