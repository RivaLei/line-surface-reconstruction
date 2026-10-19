#!/usr/bin/env python3
"""Integration checks for native checkpoint recovery (requires built binary/MOSEK)."""
import json
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    env = os.environ.copy()
    mosek = Path(env.get('MOSEK_DIR', '/home/lz/project/third_/mosek'))
    env.setdefault('MOSEKLM_LICENSE_FILE', str(mosek / 'mosek.lic'))
    env['LD_LIBRARY_PATH'] = str(mosek / '8/tools/platform/linux64x86/bin') + ':' + env.get('LD_LIBRARY_PATH', '')
    env['OMP_NUM_THREADS'] = '1'
    binary = Path(env.get('RECONS_BINARY', str(ROOT / 'build/line_based_recons')))
    with tempfile.TemporaryDirectory(prefix='recons-checkpoints-') as temporary:
        folder = Path(temporary)
        source = folder / 'input.json'
        # Include textural and structural lines, non-integer coordinates, and
        # multiple planes so topology/structural costs must survive reload.
        data = {'planes': [{'normal': [0, 0, 1], 'inlier': [0, 0, 0]},
                           {'normal': [0, 1, 0], 'inlier': [0, 0, 0]}],
                'lines': [
                    {'pt1': [-1.1234567890123, 0.4, 0], 'pt2': [1.234567890123, 0.4, 0], 'pt_views': [[0, -2, 2]], 'plane_index': [0]},
                    {'pt1': [-1, 0, 0], 'pt2': [1, 0, 0], 'pt_views': [[0, -2, 2]], 'plane_index': [0, 1]},
                    {'pt1': [-1, 0, 0.4], 'pt2': [1, 0, 0.4], 'pt_views': [[0, -2, 2]], 'plane_index': [1]}]}
        source.write_text(json.dumps(data))
        baseline = folder / 'baseline'
        baseline.mkdir()
        output = folder / 'output'
        output.mkdir()

        def run(target=output, extra=()):
            command = [str(binary), '-i', str(source), '-o', str(target), '-ext', '-v', '-cb', '1'] + list(extra)
            result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            if result.returncode:
                raise AssertionError(result.stdout)
            return result.stdout

        run(baseline, ['-nc'])
        expected = next(baseline.glob('cp_*.ply')).read_bytes()
        first = run()
        assert '[checkpoint] Saved plane arrangement.' in first
        cache = next((output / 'checkpoints').iterdir())
        weights = json.loads((cache / 'weights.json').read_text())
        model = (cache / 'model.json').read_bytes()
        geometry = (cache / 'arrangement.geometry.json').read_bytes()
        assert weights['next_line'] == 3 and weights['structural']
        assert next(output.glob('cp_*.ply')).read_bytes() == expected
        resumed = run()
        assert '[resume] Loaded plane arrangement' in resumed
        assert '[resume] Weights: 3/3' in resumed
        assert '[resume] Loaded completed optimization result.' in resumed
        assert 'Starting optimization' not in resumed
        assert next(output.glob('cp_*.ply')).read_bytes() == expected
        assert (cache / 'arrangement.geometry.json').read_bytes() == geometry

        # Remove only the completed solution: model construction must be skipped.
        (cache / 'solution.json').unlink()
        resumed = run()
        assert '[resume] Optimization terms: 5/5' in resumed
        assert next(output.glob('cp_*.ply')).read_bytes() == expected

        # Retain the first three completed terms and discard edge/corner work.
        boundary = json.loads(model)
        count = len(weights['cells'])
        structural_count = len(weights['structural'])
        facet_count = len(weights['facets'])
        constraints_count = 2*count + 2*structural_count + 4*facet_count
        variables_start = count + structural_count + len(weights['texturial']) + 2*facet_count
        boundary['stage'] = 3
        boundary['constraints'] = boundary['constraints'][:constraints_count]
        boundary['bounds'] = boundary['bounds'][:constraints_count]
        boundary['weights'][variables_start:] = [0.] * (boundary['variable_count'] - variables_start)
        (cache / 'model.json').write_text(json.dumps(boundary))
        (cache / 'solution.json').unlink()
        resumed = run()
        assert '[resume] Optimization terms: 3/5' in resumed
        assert json.loads((cache / 'model.json').read_text()) == json.loads(model)
        assert next(output.glob('cp_*.ply')).read_bytes() == expected

        # Actually interrupt a batch run, then resume its committed snapshot.
        (cache / 'solution.json').unlink()
        (cache / 'model.json').unlink()
        (cache / 'weights.json').unlink()
        # Stop a real subprocess at its first completed batch. It may finish
        # further batches before kill, so capture that exact snapshot from stdout.
        command = [str(binary), '-i', str(source), '-o', str(output), '-ext', '-cb', '1']
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        snapshot = None
        for line in process.stdout:
            if '[checkpoint] Weights: 1/3' in line:
                snapshot = json.loads((cache / 'weights.json').read_text())
                process.kill()
                break
        process.communicate()
        assert snapshot is not None
        # Restore captured committed state if the fast fixture advanced further.
        (cache / 'weights.json').write_text(json.dumps(snapshot))
        for name in ('model.json', 'solution.json'):
            path = cache / name
            if path.exists():
                path.unlink()
        resumed = run()
        assert '[resume] Weights: {}/3'.format(snapshot['next_line']) in resumed
        assert next(output.glob('cp_*.ply')).read_bytes() == expected
        final_weights = json.loads((cache / 'weights.json').read_text())
        assert final_weights == weights

        # Concurrent writers must not modify an active checkpoint directory.
        with (cache / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            command = [str(binary), '-i', str(source), '-o', str(output), '-ext']
            conflict = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
            assert conflict.returncode != 0 and 'already in use' in conflict.stdout

        # Parameter and input changes must select a fresh cache namespace.
        changed = run(extra=['-ce', '0.2'])
        assert '[checkpoint] Saved plane arrangement.' in changed
        data['lines'][0]['pt_views'][0][2] = 3
        source.write_text(json.dumps(data))
        changed = run()
        assert '[checkpoint] Saved plane arrangement.' in changed
        assert len(list((output / 'checkpoints').iterdir())) == 3
        print('PASS: exact geometry, structural/textural weights, partial-batch interruption, model/solution reuse, input/parameter invalidation, and baseline PLY consistency')


if __name__ == '__main__':
    main()
