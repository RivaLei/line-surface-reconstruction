#!/usr/bin/env bash
###
 # @Author: riva-ubuntu-privite 961095446@qq.com
 # @Date: 2026-10-19 10:43:05
 # @LastEditors: riva-ubuntu-privite 961095446@qq.com
 # @LastEditTime: 2026-10-19 11:20:55
 # @FilePath: /line-surface-reconstruction/scripts/custom.sh
 # @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
### 
# OBJ + LIMAP preparation / reconstruction. See custom.md.
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
obj_path="${OBJ:-/home/lz/dataL/sztu12/sztu12/triangulated_lines_nv4_clipped.obj}"
limap_path="${LIMAP_DIR:-/home/lz/project/limap-old/outputs/sztu12}"
dataset_name="${NAME:-sztu12}"
mode="${1:-all}"
if [[ $# -gt 0 ]]; then
    shift
fi
case "$mode" in
    prepare)
        exec "$script_dir/scripts/custom_demo" --obj "$obj_path" --limap-dir "$limap_path" \
            --name "$dataset_name" "$@" --prepare-only
        ;;
    reconstruct)
        exec "$script_dir/scripts/custom_demo" --name "$dataset_name" "$@"
        ;;
    all)
        exec "$script_dir/scripts/custom_demo" --obj "$obj_path" --limap-dir "$limap_path" \
            --name "$dataset_name" "$@"
        ;;
    -h|--help|help)
        cat <<'HELP'
Usage: ./custom.sh [prepare|reconstruct|all] [custom_demo options]
  prepare      Generate JSON and inspection OBJ only.
  reconstruct  Reuse final JSON and run reconstruction.
  all          Prepare input and run reconstruction (default).
Defaults may be overridden with OBJ, LIMAP_DIR, NAME, PYTHON or CLI options.
See scripts/custom.md for inputs, output paths and validation details.
HELP
        ;;
    *)
        echo "Unknown mode: $mode (expected prepare, reconstruct or all)" >&2
        exit 2
        ;;
esac
