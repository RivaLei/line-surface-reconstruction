"""Checks for final-input reuse and incomplete-input fallback."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import custom_demo as demo


class CustomDemoTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.folder = self.root / 'data/sample'
        self.folder.mkdir(parents=True)
        self.final = self.folder / 'input_lines_from_residuals.json'
        self.obj = self.root / 'lines.obj'
        self.obj.write_text('v 0 0 0\nv 1 0 0\nl 1 2\n')
        self.data = {'lines': [{'pt1': [0, 0, 0], 'pt2': [1, 0, 0],
                                'pt_views': [[0, 0, 10]], 'plane_index': [0]}],
                     'planes': [{'normal': [0, 0, 1], 'inlier': [0, 0, 0]}]}
        self.addCleanup(self.temp.cleanup)

    def invoke(self, *extra):
        argv = ['custom_demo', '--name', 'sample', '--obj', str(self.obj)] + list(extra)
        with patch.object(demo, 'ROOT', self.root), patch('sys.argv', argv):
            return demo.main()

    def fake_ransac(self, command, env):
        self.assertEqual(Path(command[0]).name, 'ransac_on_lines')
        data = copy.deepcopy(self.data)
        data['lines'][0]['pt_views'] = None  # Actual C++ empty-vector serialization.
        (self.folder / 'test_input_for_reconstruction.json').write_text(json.dumps(data))

    def test_complete_final_skips_sources_and_runs_reconstruction(self):
        self.final.write_text(json.dumps(self.data))
        self.obj.unlink()  # Complete JSON must work without the source OBJ.
        with patch.object(demo, 'run') as run:
            self.assertEqual(self.invoke(), 0)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(Path(run.call_args[0][0][0]).name, 'line_based_recons')
            self.assertIn('-sa', run.call_args[0][0])
        self.assertTrue((self.root / 'result/demo-sample/lines_by_plane.obj').exists())
        self.assertFalse((self.folder / 'input_lines.json').exists())

    def test_missing_final_generates_intermediates_only(self):
        with patch.object(demo, 'run', side_effect=self.fake_ransac) as run:
            self.assertEqual(self.invoke('--prepare-only'), 0)
            self.assertEqual(run.call_count, 1)
        self.assertTrue((self.folder / 'input_lines.json').exists())
        plane = json.loads((self.folder / 'input_planes.json').read_text())
        self.assertEqual(plane['lines'][0]['pt_views'], [])
        self.assertFalse(self.final.exists())

    def test_corrupt_final_falls_back_without_launching_reconstruction(self):
        self.final.write_text('{broken')
        with patch.object(demo, 'run', side_effect=self.fake_ransac) as run:
            self.assertEqual(self.invoke(), 1)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(self.final.read_text(), '{broken')
        self.assertTrue((self.folder / 'input_planes.json').exists())

    def test_validation_rejects_missing_views_bad_indices_and_nonunit_normals(self):
        demo.validate_reconstruction(self.data)
        for modify in (lambda d: d['lines'][0].update(pt_views=[]),
                       lambda d: d['lines'][0].update(plane_index=[1]),
                       lambda d: d['planes'][0].update(normal=[0, 0, 2]),
                       lambda d: d['lines'][0].update(pt1=[float('nan'), 0, 0])):
            data = copy.deepcopy(self.data)
            modify(data)
            with self.assertRaises(ValueError):
                demo.validate_reconstruction(data)


class ObservationTest(unittest.TestCase):
    def test_projection_pose_crop_and_parallel(self):
        import numpy as np
        r = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
        center = np.array([3., 4., -10.])
        cam = (r, -r @ center, center, np.eye(3))
        a, b = np.array([0., 0., 0.]), np.array([10., 0., 0.])
        def pixel(point):
            q = r @ (point-center)
            return q[:2]/q[2]
        pixels = np.r_[pixel(np.array([-2., 0., 0.])), pixel(np.array([8., 0., 0.]))]
        first, second = demo.project_observation(a, b, pixels, cam)
        np.testing.assert_allclose(first, [.2, 0, 0], atol=1e-12)
        np.testing.assert_allclose(second, [7.8, 0, 0], atol=1e-12)
        self.assertIsNone(demo.project_observation(np.array([0.,0.,1.]),np.array([0.,0.,2.]),[0,0,0,0],(np.eye(3),np.zeros(3),np.zeros(3),np.eye(3))))

    def test_cropped_reversed_matching_and_multiple_observations(self):
        import numpy as np
        camera = (np.eye(3), np.zeros(3), np.zeros(3), np.eye(3))
        track = (7, np.array([0.,0.,10.]),np.array([10.,0.,10.]),[2,2],[4,5],np.array([[0,0,1,0],[0,0,.5,0]]))
        data = {'lines':[{'pt1':[8.,0.,10.],'pt2':[2.,0.,10.]}]}
        with patch.object(demo,'read_limap_tracks',return_value=[track]), patch.object(demo,'limap_cameras',return_value={2:camera}):
            demo.attach_limap_views(data,Path('/unused'),1e-6)
            self.assertEqual(len(data['lines']),2)
            self.assertEqual([x['line_id'] for x in data['lines']],[4,5])
            for line in data['lines']:
                self.assertEqual(len(line['pt_views']),1)
                self.assertTrue(2 <= line['pt1'][0] <= 8)
            with patch.object(demo,'read_limap_tracks',return_value=[track,track]):
                with self.assertRaises(ValueError):
                    demo.attach_limap_views({'lines':[{'pt1':[8.,0.,10.],'pt2':[2.,0.,10.]}]},Path('/unused'),1e-6)

if __name__ == '__main__':
    unittest.main()
