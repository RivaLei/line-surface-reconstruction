"""Export plane-colored lines without changing reconstruction inputs."""
import colorsys
import json
import math
from pathlib import Path


def plane_color(index):
    if index < 0:
        return (150, 150, 150)
    return tuple(round(255*x) for x in colorsys.hsv_to_rgb((index*0.618033988749895) % 1., .72, .95))


def export_plane_lines(input_path, output_dir):
    """Write OBJ/MTL, edge PLY and a legend; two-plane lines use two halves."""
    with Path(input_path).open() as stream:
        data = json.load(stream)
    planes, lines = data['planes'], data['lines']
    segments, counts = [], {i: 0 for i in range(-1, len(planes))}
    for index, line in enumerate(lines):
        a, b = line['pt1'], line['pt2']
        if any(len(p) != 3 or any(not math.isfinite(x) for x in p) for p in (a, b)):
            raise ValueError(f'Line {index}: invalid coordinates')
        ids = sorted(set(line.get('plane_index') or []))
        if len(ids) > 2 or any(type(i) is not int or not 0 <= i < len(planes) for i in ids):
            raise ValueError(f'Line {index}: invalid plane_index')
        ids = ids or [-1]
        for plane in ids:
            counts[plane] += 1
        if len(ids) == 2:
            mid = [(x+y)/2 for x, y in zip(a, b)]
            segments.extend([(a, mid, ids[0]), (mid, b, ids[1])])
        else:
            segments.append((a, b, ids[0]))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    obj = output_dir / 'lines_by_plane.obj'
    with obj.open('w') as stream:
        stream.write('# Two-plane lines are split at their midpoint for coloring only.\nmtllib lines_by_plane.mtl\n')
        for a, b, plane in segments:
            for point in (a, b):
                stream.write('v ' + ' '.join(format(x, '.17g') for x in point) + '\n')
        for i, (_, _, plane) in enumerate(segments):
            stream.write(f'usemtl plane_{plane}\nl {2*i+1} {2*i+2}\n')
    with obj.with_suffix('.mtl').open('w') as stream:
        for plane in counts:
            rgb = ' '.join(format(c/255., '.8f') for c in plane_color(plane))
            stream.write(f'newmtl plane_{plane}\nKa {rgb}\nKd {rgb}\nd 1\nillum 0\n\n')
    with obj.with_suffix('.ply').open('w') as stream:
        stream.write('ply\nformat ascii 1.0\ncomment plane -1 means unassigned\n')
        stream.write(f'element vertex {2*len(segments)}\nproperty double x\nproperty double y\nproperty double z\n')
        stream.write('property uchar red\nproperty uchar green\nproperty uchar blue\n')
        stream.write(f'element edge {len(segments)}\nproperty int vertex1\nproperty int vertex2\nproperty int plane_index\nend_header\n')
        for a, b, plane in segments:
            color = ' '.join(map(str, plane_color(plane)))
            for point in (a, b):
                stream.write(' '.join(format(x, '.17g') for x in point) + ' ' + color + '\n')
        for i, (_, _, plane) in enumerate(segments):
            stream.write(f'{2*i} {2*i+1} {plane}\n')
    legend = {'source': str(input_path), 'input_lines': len(lines), 'display_segments': len(segments),
              'two_plane_rule': 'first half: lower plane index; second half: higher plane index',
              'planes': [{'plane_index': i, 'rgb': plane_color(i), 'line_count': count,
                          'plane': planes[i] if i >= 0 else None} for i, count in counts.items()]}
    obj.with_suffix('.json').write_text(json.dumps(legend, indent=2) + '\n')
    print(f'Plane-colored lines: {obj} ({len(lines)} input lines, {len(segments)} display segments)', flush=True)
    return obj
