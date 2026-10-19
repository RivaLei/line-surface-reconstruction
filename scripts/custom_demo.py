#!/usr/bin/env python3
"""从裁剪 OBJ 和 LIMAP 完整 track 逐观测生成线段、平面及重建输入。

未提供 LIMAP 时保留旧版几何回退；缺少观测时不生成最终输入。
--limap-dir 指定 LIMAP 输出；显式指定时重新准备，--reuse-final 可复用已有最终输入。
--prepare-only 只检查/准备数据，不执行重建。
"""
import argparse
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys

from plane_visualization import export_plane_lines

ROOT = Path(__file__).resolve().parent.parent


def read_obj(path, viewpoints):
    """读取 OBJ 顶点和线段，保留原始坐标，不推断相机位置或平面。

    viewpoints 是用户提供的共享相机中心列表，会应用到每条线段。
    只有这些相机都确实观测到所有线段时才适用；通常应从原始观测
    数据中恢复每条线段各自的相机列表。OBJ 本身不含这些信息。
    """
    vertices, segments = [], []
    with path.open() as stream:
        for number, raw in enumerate(stream, 1):
            fields = raw.split('#', 1)[0].split()
            if not fields:
                continue
            try:
                if fields[0] == 'v':
                    # v x y z：顶点三维坐标，与后续相机中心须处于同一坐标系。
                    point = [float(value) for value in fields[1:4]]
                    if len(point) != 3 or not all(map(math.isfinite, point)):
                        raise ValueError('expected three finite coordinates')
                    vertices.append(point)
                elif fields[0] == 'l':
                    # l i j 或 l i j k ...：顶点索引；也兼容 i/纹理索引写法。
                    indices = [int(value.split('/')[0]) for value in fields[1:]]
                    if len(indices) < 2:
                        raise ValueError('line needs at least two vertices')
                    points = []
                    for index in indices:
                        # OBJ 正索引从 1 开始，负索引相对当前已读取的顶点末尾。
                        resolved = index - 1 if index > 0 else len(vertices) + index
                        if index == 0 or not 0 <= resolved < len(vertices):
                            raise ValueError(f'invalid vertex index {index}')
                        points.append(vertices[resolved])
                    for first, second in zip(points, points[1:]):
                        # 折线按相邻顶点拆为独立线段，并跳过零长度段。
                        if first != second:
                            # pt1/pt2：端点；pt_views：观测相机中心；
                            # plane_index：所属平面的零基索引，此时尚未检测。
                            segments.append({'pt1': first, 'pt2': second,
                                             'pt_views': viewpoints, 'plane_index': []})
            except ValueError as error:
                raise ValueError(f'{path}:{number}: {error}') from error
    if not segments:
        raise ValueError('OBJ contains no nonzero line segments (l records)')
    # 步骤一仅提供线段；planes 将在步骤二通过 RANSAC 计算。
    return {'lines': segments, 'planes': []}


def run(command, env):
    print(' '.join(shlex.quote(str(part)) for part in command), flush=True)
    subprocess.run(list(map(str, command)), cwd=ROOT, env=env, check=True)


def read_limap_tracks(folder):
    """Read full tracks, including subpixel 2D observations (not alltracks IDs)."""
    import numpy as np
    paths = sorted((folder / 'finaltracks').glob('track_*.txt'))
    if not paths:
        raise ValueError(f'Missing finaltracks/track_*.txt under {folder}')
    tracks = []
    for path in paths:
        with path.open() as stream:
            ends = np.asarray(list(map(float, stream.readline().split())))
            count, n_images = map(int, stream.readline().split())
            image_row, line_row = stream.readline().split(), stream.readline().split()
            if image_row[0] != 'image_id_list' or line_row[0] != 'line_id_list' or stream.readline().strip() != 'line2d_list':
                raise ValueError(f'Unsupported track layout: {path}')
            image_ids, line_ids = list(map(int, image_row[1:])), list(map(int, line_row[1:]))
            observations = np.asarray([list(map(float, stream.readline().split())) for _ in range(count)])
        if (ends.shape != (6,) or not np.isfinite(ends).all()
                or count <= 0 or observations.shape != (count, 4)
                or not np.isfinite(observations).all() or len(image_ids) != count
                or len(line_ids) != count or len(set(image_ids)) != n_images
                or np.linalg.norm(ends[3:] - ends[:3]) == 0):
            raise ValueError(f'Invalid track: {path}')
        tracks.append((int(path.stem.split('_')[1]), ends[:3], ends[3:], image_ids, line_ids, observations))
    return tracks


def limap_cameras(folder):
    """Pixel coordinates must correspond to these undistorted pinhole cameras."""
    import numpy as np
    source = folder / 'finaltracks/imagecols.npy'
    if not source.exists():
        source = folder / 'imagecols.npy'
    model = np.load(source, allow_pickle=True).item()
    result = {}
    for image_id, image in model['images'].items():
        camera = model['cameras'][image['cam_id']]
        params = camera['params']
        if camera['model_id'] == 0 and len(params) == 3:
            fx, cx, cy = params
            fy = fx
        elif camera['model_id'] == 1 and len(params) == 4:
            fx, fy, cx, cy = params
        else:
            raise ValueError(f'Image {image_id}: require undistorted SIMPLE_PINHOLE/PINHOLE camera')
        q, t = np.asarray(image['qvec'], dtype=float), np.asarray(image['tvec'], dtype=float)
        if (q.shape != (4,) or t.shape != (3,) or not np.isfinite(q).all()
                or not np.isfinite(t).all() or np.linalg.norm(q) == 0
                or not np.isfinite([fx, fy, cx, cy]).all() or min(fx, fy) <= 0):
            raise ValueError(f'Invalid camera for image {image_id}')
        w, x, y, z = q / np.linalg.norm(q)
        rotation = np.array([
            [1-2*y*y-2*z*z, 2*x*y-2*w*z, 2*x*z+2*w*y],
            [2*x*y+2*w*z, 1-2*x*x-2*z*z, 2*y*z-2*w*x],
            [2*x*z-2*w*y, 2*y*z+2*w*x, 1-2*x*x-2*y*y]])
        result[int(image_id)] = (rotation, t, -rotation.T @ t,
                                np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]]))
    return result


def project_observation(first, second, pixels, camera):
    """Closest points on the 3D line to the two camera rays, then clip.

    Intersect with the input OBJ segment before applying the official 5% total
    endpoint shrink. Return None for parallel rays, behind-camera or empty spans.
    """
    import numpy as np
    rotation, translation, center, intrinsic = camera
    a = rotation @ first + translation
    direction = rotation @ (second - first)
    length2 = direction @ direction
    parameters = []
    for pixel in np.asarray(pixels).reshape(2, 2):
        ray = np.linalg.solve(intrinsic, [pixel[0], pixel[1], 1.0])
        rr, dr, da = ray @ ray, direction @ ray, direction @ a
        denominator = length2 * rr - dr * dr
        if denominator <= 1e-12 * length2 * rr:
            return None
        parameter = (dr * (a @ ray) - rr * da) / denominator
        if (a + parameter * direction)[2] <= 0:
            return None
        parameters.append(parameter)
    lo, hi = max(0., min(parameters)), min(1., max(parameters))
    if hi - lo <= 1e-10:
        return None
    offset = (hi - lo) * 0.025
    direction_world = second - first
    return first + (lo + offset) * direction_world, first + (hi - offset) * direction_world


def attach_limap_views(data, folder, tolerance):
    """Match cropped OBJ segments and expand each into individual observations."""
    import numpy as np
    tracks, cameras = read_limap_tracks(folder), limap_cameras(folder)
    firsts = np.asarray([track[1] for track in tracks])
    seconds = np.asarray([track[2] for track in tracks])
    directions = seconds - firsts
    lengths = np.linalg.norm(directions, axis=1)
    units = directions / lengths[:, None]
    output, rejected, mapping = [], 0, []
    for index, line in enumerate(data['lines']):
        a, b = np.asarray(line['pt1']), np.asarray(line['pt2'])
        exact = np.minimum(np.maximum(np.linalg.norm(firsts-a, axis=1), np.linalg.norm(seconds-b, axis=1)),
                           np.maximum(np.linalg.norm(firsts-b, axis=1), np.linalg.norm(seconds-a, axis=1))) <= tolerance
        matches = np.flatnonzero(exact)
        if not len(matches):
            # Both endpoints must lie on and inside the original track segment.
            ta = np.sum((a-firsts)*units, axis=1)
            tb = np.sum((b-firsts)*units, axis=1)
            distance_a = np.linalg.norm(a-firsts-ta[:, None]*units, axis=1)
            distance_b = np.linalg.norm(b-firsts-tb[:, None]*units, axis=1)
            matches = np.flatnonzero((distance_a <= tolerance) & (distance_b <= tolerance)
                                    & (np.minimum(ta, tb) >= -tolerance)
                                    & (np.maximum(ta, tb) <= lengths+tolerance))
        if len(matches) != 1:
            raise ValueError(f'OBJ segment {index}: expected one track, found {len(matches)}; check coordinates/tolerance or supply an unambiguous crop')
        track_id, _, _, image_ids, line_ids, observations = tracks[int(matches[0])]
        start = len(output)
        for image_id, line_id, pixels in zip(image_ids, line_ids, observations):
            if image_id not in cameras:
                raise ValueError(f'Track {track_id}: missing image {image_id}')
            endpoints = project_observation(a, b, pixels, cameras[image_id])
            if endpoints is None:
                rejected += 1
                continue
            first, second = endpoints
            output.append({'pt1': first.tolist(), 'pt2': second.tolist(),
                           'pt_views': [cameras[image_id][2].tolist()], 'plane_index': [],
                           'obj_segment_id': index, 'limap_track_id': track_id,
                           'image_ids': [image_id], 'line_id': line_id,
                           'line2d': pixels.tolist()})
        if len(output) == start:
            raise ValueError(f'OBJ segment {index}, track {track_id}: no valid observations after projection/cropping')
        mapping.append({'obj_segment_id': index, 'limap_track_id': track_id,
                        'observations': len(output)-start})
    data['lines'] = output
    data['preparation'] = {'limap_dir': str(folder), 'method': 'limap_per_observation_v1', 'clipped_to_obj': True,
                           'endpoint_shrink': 0.05, 'rejected_observations': rejected,
                           'mapping': mapping}
    print(f'Expanded {len(mapping)} OBJ segments into {len(output)} observations; rejected {rejected}', flush=True)


def validate_reconstruction(data, require_views=True):
    """检查 C++ 重建所需字段；允许未归属平面的线段，但须有有效关联。"""
    def vector(value):
        return (isinstance(value, list) and len(value) == 3
                and all(type(x) in (int, float) and math.isfinite(x) for x in value))

    if not isinstance(data, dict):
        raise ValueError('JSON root must be an object')
    planes, lines = data.get('planes'), data.get('lines')
    if not isinstance(planes, list) or not planes:
        raise ValueError('planes must be a nonempty array')
    if not isinstance(lines, list) or not lines:
        raise ValueError('lines must be a nonempty array')
    for i, plane in enumerate(planes):
        if not isinstance(plane, dict) or not vector(plane.get('normal')) or not vector(plane.get('inlier')):
            raise ValueError(f'planes[{i}]: invalid normal/inlier')
        if abs(sum(x*x for x in plane['normal']) - 1) >= 1e-10:
            raise ValueError(f'planes[{i}]: normal must have unit length')
    associated = False
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or not vector(line.get('pt1')) or not vector(line.get('pt2')) or line['pt1'] == line['pt2']:
            raise ValueError(f'lines[{i}]: invalid or zero-length endpoints')
        indices = line.get('plane_index')
        if (not isinstance(indices, list) or len(indices) > 2
                or any(type(j) is not int or not 0 <= j < len(planes) for j in indices)
                or len(set(indices)) != len(indices)):
            raise ValueError(f'lines[{i}]: invalid plane_index')
        associated = associated or bool(indices)
        views = line.get('pt_views')
        if not isinstance(views, list) or (require_views and not views) or not all(vector(v) for v in views):
            raise ValueError(f'lines[{i}]: missing/invalid pt_views')
    if not associated:
        raise ValueError('No line is associated with a plane')


def write_line_obj(json_path):
    """Export exactly the final JSON endpoints as OBJ v/l records."""
    data = json.loads(json_path.read_text())
    with json_path.with_suffix('.obj').open('w') as stream:
        for line in data['lines']:
            for key in ('pt1', 'pt2'):
                stream.write('v ' + ' '.join(format(x, '.17g') for x in line[key]) + '\n')
        for i in range(len(data['lines'])):
            stream.write(f'l {2*i+1} {2*i+2}\n')


def run_reconstruction(args, input_path, output_dir, env):
    export_plane_lines(input_path, output_dir)
    if args.prepare_only:
        return 0
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [ROOT / 'build/line_based_recons', '-i', input_path, '-o', str(output_dir) + '/']
    for name in ('cp', 'cv', 'ca', 'ce', 'cc'):
        command.extend(['-' + name, getattr(args, name)])
    command.extend(['--bbox-source', args.bbox_source])
    run(command + ['-' + args.scene, '-sa', '-v'], env)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--obj', type=Path, default=Path('/home/lz/dataL/sztu12/sztu12/triangulated_lines_nv4_clipped.obj'))
    parser.add_argument('--name', default='sztu12')
    parser.add_argument('--bbox-source', choices=['camera', 'line'], default='camera',
                        help='camera: line endpoints and camera centers (default); line: endpoints only, with _line_box output suffix')
    parser.add_argument('--limap-dir', '--limap_dir', '--limap-output', dest='limap_output', type=Path, help='LIMAP output containing finaltracks and imagecols.npy; regenerate per-observation input')
    parser.add_argument('--reuse-final', action='store_true', help='reuse complete final JSON even when LIMAP sources are supplied')
    parser.add_argument('--no-limap', action='store_true', help='disable per-line LIMAP camera observations')
    parser.add_argument('--match-tolerance', type=float, default=1e-6, help='endpoint matching tolerance in OBJ units')
    parser.add_argument('--prepare-only', action='store_true', help='generate reconstruction JSON without running reconstruction')
    parser.add_argument('--viewpoint', type=float, nargs=3, action='append', default=[], metavar=('X', 'Y', 'Z'), help='camera center in OBJ coordinates; repeat for multiple views (applied to all lines)')
    parser.add_argument('--epsilon', type=float, default=0.02, help='RANSAC distance tolerance in OBJ units')
    parser.add_argument('--iterations', type=int, default=1000)
    parser.add_argument('--max-planes', type=int, default=30)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--scene', choices=['ext', 'int'], default='ext')
    for name, default in [('cp', 1), ('cv', 1), ('ca', 0), ('ce', 0.1), ('cc', 0.1)]:
        parser.add_argument('--' + name, type=float, default=default)
    args = parser.parse_args()
    if args.viewpoint and args.limap_output and not args.no_limap:
        parser.error('choose either --viewpoint or --limap-output')
    if not math.isfinite(args.match_tolerance) or args.match_tolerance <= 0:
        parser.error('--match-tolerance must be finite and positive')
    if args.name in ('.', '..') or Path(args.name).name != args.name:
        parser.error('--name must be a single directory name')
    if not math.isfinite(args.epsilon) or args.epsilon <= 0 or args.iterations <= 0 or args.max_planes <= 0:
        parser.error('epsilon, iterations and max-planes must be positive')
    if not all(math.isfinite(v) for point in args.viewpoint for v in point):
        parser.error('viewpoints must be finite')
    data_dir = ROOT / 'data' / args.name
    output_name = 'demo-' + args.name + ('_line_box' if args.bbox_source == 'line' else '')
    output_dir = ROOT / 'result' / output_name

    # 沿用 test_demo.py 的 MOSEK 运行环境，并允许已有环境变量覆盖路径。
    env = os.environ.copy()
    env.setdefault('OMP_NUM_THREADS', '3')
    mosek = Path(env.get('MOSEK_DIR', '/home/lz/project/third_/mosek'))
    env['MOSEK_DIR'] = str(mosek)
    env.setdefault('MOSEKLM_LICENSE_FILE', str(mosek / 'mosek.lic'))
    env['LD_LIBRARY_PATH'] = str(mosek / '8/tools/platform/linux64x86/bin') + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    # 先检查最终输入；完整时直接进入重建，不访问 OBJ、LIMAP 或重新拟合。
    input_path = data_dir / 'input_lines_from_residuals.json'
    try:
        if args.limap_output and not args.no_limap and not args.reuse_final:
            raise ValueError('Explicit LIMAP source: rebuilding per-observation input')
        validate_reconstruction(json.loads(input_path.read_text()))
    except (OSError, ValueError) as error:
        print(f'Final JSON unavailable/incomplete: {error}', flush=True)
    else:
        write_line_obj(input_path)
        print(f'Using complete reconstruction JSON: {input_path}', flush=True)
        return run_reconstruction(args, input_path, output_dir, env)

    # ===== 步骤一：OBJ -> input_lines.json =====
    # 默认只有几何数据、pt_views=[]；仅在显式指定来源时尝试恢复视点。
    data = read_obj(args.obj.expanduser().resolve(), args.viewpoint)
    data_dir.mkdir(parents=True, exist_ok=True)
    raw_path = data_dir / 'input_lines.json'
    raw_path.write_text(json.dumps(data, allow_nan=False) + '\n')
    if args.limap_output and not args.no_limap:
        attach_limap_views(data, args.limap_output.expanduser().resolve(), args.match_tolerance)
        raw_path.write_text(json.dumps(data, allow_nan=False) + '\n')
    print(f'Converted {len(data["lines"])} segments -> {raw_path}', flush=True)
    # ===== 步骤二：线段 JSON -> input_planes.json（平面及线段关联）=====
    # -e：距离容差（OBJ 单位）；-n：采样迭代数；-np：平面数量限制。
    # RANSAC 生成 planes（单位 normal、平面上一点 inlier），并为每条线段
    # 填入 plane_index；相机观测只沿用输入，不会由平面检测恢复。
    run([ROOT / 'build/ransac_on_lines', '-i', raw_path, '-o', data_dir,
         '-e', args.epsilon, '-n', args.iterations, '-np', args.max_planes, '-s', args.seed, '-v'], env)
    # C++ 程序使用固定输出名，另会生成 test_no_refine... 的未精化版本。
    detected = json.loads((data_dir / 'test_input_for_reconstruction.json').read_text())
    if not detected.get('planes'):
        raise ValueError('RANSAC detected no planes; adjust --epsilon/--iterations')
    # C++ 写出器会把空视点向量序列化成 null；这里统一为空数组。
    for line in detected['lines']:
        line['pt_views'] = line.get('pt_views') or []
        line['plane_index'] = line.get('plane_index') or []
    # 当前 C++ RANSAC 保持线段顺序和端点，但不保留自定义来源字段。
    # 核对后补回 track/image ID，便于检查最终 JSON 的视点来源。
    if len(detected['lines']) != len(data['lines']):
        raise ValueError('RANSAC changed the number of lines')
    for original, line in zip(data['lines'], detected['lines']):
        if original['pt1'] != line['pt1'] or original['pt2'] != line['pt2']:
            raise ValueError('RANSAC changed line order or coordinates')
        for key in ('limap_track_id', 'image_ids', 'obj_segment_id', 'line_id', 'line2d'):
            if key in original:
                line[key] = original[key]
    if 'preparation' in data:
        detected['preparation'] = data['preparation']
    # 平面中间文件允许 pt_views=[]；不冒充完整重建输入。
    validate_reconstruction(detected, require_views=False)
    plane_path = data_dir / 'input_planes.json'
    plane_path.write_text(json.dumps(detected, allow_nan=False) + '\n')
    print(f'Prepared {len(detected["planes"])} planes -> {plane_path}', flush=True)
    try:
        validate_reconstruction(detected)
    except ValueError as error:
        print(f'Stopped after plane fitting: {error}. Final JSON was not generated; reconstruction was not started.', file=sys.stderr)
        # prepare-only 已完成中间数据准备；直接运行则以非零状态表示未能重建。
        return 0 if args.prepare_only else 1
    # 仅当视点和几何字段全部完整时写入最终 JSON，沿用官方文件名。
    # LIMAP 分支已经按二维观测反投影；共享视点旧分支仅保留原始几何。
    input_path.write_text(json.dumps(detected, allow_nan=False) + '\n')
    write_line_obj(input_path)
    print(f'Prepared complete reconstruction JSON and OBJ -> {input_path}', flush=True)
    return run_reconstruction(args, input_path, output_dir, env)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, ImportError, subprocess.CalledProcessError) as error:
        print(f'custom_demo: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
