import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from plane_visualization import export_plane_lines, plane_color
import test_demo


class PlaneVisualizationTest(unittest.TestCase):
    def test_membership_colors_indices_and_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'input.json'
            data = {'planes': [{}, {}], 'lines': [
                {'pt1': [0,0,0], 'pt2': [2,0,0], 'plane_index': []},
                {'pt1': [0,1,0], 'pt2': [2,1,0], 'plane_index': [0]},
                {'pt1': [0,2,0], 'pt2': [2,2,0], 'plane_index': [1,0]}]}
            source.write_text(json.dumps(data))
            obj = export_plane_lines(source, root/'out')
            self.assertEqual(json.loads(source.read_text()), data)
            rows = obj.read_text().splitlines()
            vertices = [list(map(float, r.split()[1:])) for r in rows if r.startswith('v ')]
            self.assertEqual(vertices[-4:], [[0,2,0],[1,2,0],[1,2,0],[2,2,0]])
            self.assertEqual([r for r in rows if r.startswith('l ')], ['l 1 2','l 3 4','l 5 6','l 7 8'])
            self.assertEqual([r for r in rows if r.startswith('usemtl')], ['usemtl plane_-1','usemtl plane_0','usemtl plane_0','usemtl plane_1'])
            legend = json.loads(obj.with_suffix('.json').read_text())
            self.assertEqual(legend['input_lines'],3)
            self.assertEqual(legend['display_segments'],4)
            ply = obj.with_suffix('.ply').read_text().split('end_header\n')[1].splitlines()
            self.assertEqual(len(ply),12)
            self.assertEqual(list(map(int,ply[0].split()[3:])),list(plane_color(-1)))
            self.assertEqual(ply[-1],'6 7 1')

    def test_official_demo_enables_both_outputs(self):
        with patch.object(test_demo, 'export_plane_lines') as export, patch.object(test_demo.subprocess, 'run') as run, patch.object(Path,'mkdir'):
            run.return_value.returncode = 0
            self.assertEqual(test_demo.main(),0)
            export.assert_called_once()
            self.assertIn('-sa',run.call_args[0][0])
