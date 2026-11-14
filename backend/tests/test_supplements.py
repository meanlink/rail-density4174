"""补发、更正、撤销与输入快照的回归测试。

运行方式（在 backend/ 目录）：
    DATABASE_URL=sqlite:////tmp/supplement-test.db ARTIFACT_DIR=/tmp/artifacts \
        PYTHONPATH=. python3 -m unittest tests.test_supplements -v
"""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('DATABASE_URL', 'sqlite:////tmp/supplement-test.db')
os.environ.setdefault('ARTIFACT_DIR', '/tmp/artifacts')

from fastapi.testclient import TestClient  # noqa: E402

from src.main import app  # noqa: E402
import src.worker as worker  # noqa: E402


class SupplementFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()
        cls.auth = {}
        for role in ('analyst', 'viewer', 'admin'):
            response = cls.client.post('/auth/login', json={'email': f'{role}@demo.local', 'password': 'Demo123!'})
            cls.auth[role] = {'Authorization': 'Bearer ' + response.json()['access_token']}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def _dataset(self, rows):
        response = self.client.post('/datasets', headers=self.auth['analyst'],
                                    json={'name': '测试批次 · ' + self._testMethodName, 'source': 't.csv', 'records': rows})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['id']

    def _supplement(self, dataset_id, records, role='analyst'):
        return self.client.post(f'/datasets/{dataset_id}/supplements', headers=self.auth[role],
                                json={'source': 'supplement.json', 'records': records})

    def _detail(self, dataset_id):
        return self.client.get(f'/datasets/{dataset_id}', headers=self.auth['analyst']).json()

    def _rows(self, count=15):
        return [{'defect_id': f'D{i:03}', 'mileage_km': float(i), 'lateral_mm': 1.0, 'severity': 2} for i in range(1, count + 1)]

    def test_supplement_counts_and_effects(self):
        dataset_id = self._dataset(self._rows())
        response = self._supplement(dataset_id, [
            {'defect_id': 'D100', 'revision': 1, 'mileage_km': 100.0, 'lateral_mm': 2, 'severity': 3},
            {'defect_id': 'D002', 'revision': 2, 'mileage_km': 2.5, 'lateral_mm': 9, 'severity': 5},
            {'defect_id': 'D003', 'revision': 2, 'revoked': True},
            {'defect_id': 'D001', 'revision': 1, 'mileage_km': 1.0, 'lateral_mm': 1, 'severity': 2},
        ])
        self.assertEqual(response.status_code, 201, response.text)
        supplement = response.json()['supplement']
        self.assertEqual((supplement['added'], supplement['corrected'], supplement['revoked'], supplement['ignored']), (1, 1, 1, 1))
        detail = self._detail(dataset_id)
        ids = {row['defect_id'] for row in detail['records']}
        self.assertIn('D100', ids)
        self.assertNotIn('D003', ids)
        corrected = next(row for row in detail['records'] if row['defect_id'] == 'D002')
        self.assertEqual(corrected['mileage_km'], 2.5)
        self.assertEqual(len(detail['supplements']), 2)

    def test_duplicate_delivery_adds_nothing(self):
        dataset_id = self._dataset(self._rows())
        payload = [{'defect_id': 'D500', 'revision': 1, 'mileage_km': 50.0, 'lateral_mm': 1, 'severity': 2}]
        self.assertEqual(self._supplement(dataset_id, payload).status_code, 201)
        before = self._detail(dataset_id)
        second = self._supplement(dataset_id, payload).json()['supplement']
        self.assertEqual((second['added'], second['corrected'], second['revoked'], second['ignored']), (0, 0, 0, 1))
        after = self._detail(dataset_id)
        self.assertEqual(before['checksum'], after['checksum'])
        self.assertEqual(before['records'], after['records'])

    def test_late_old_revision_cannot_revive_revoked_point(self):
        dataset_id = self._dataset(self._rows())
        self._supplement(dataset_id, [{'defect_id': 'D004', 'revision': 2, 'revoked': True}])
        response = self._supplement(dataset_id, [{'defect_id': 'D004', 'revision': 1, 'mileage_km': 4.0, 'lateral_mm': 1, 'severity': 2}])
        supplement = response.json()['supplement']
        self.assertEqual((supplement['added'], supplement['ignored']), (0, 1))
        self.assertNotIn('D004', {row['defect_id'] for row in self._detail(dataset_id)['records']})

    def test_same_pair_conflict_rejects_whole_delivery(self):
        dataset_id = self._dataset(self._rows())
        before = self._detail(dataset_id)
        response = self._supplement(dataset_id, [
            {'defect_id': 'D006', 'revision': 2, 'mileage_km': 6.0, 'lateral_mm': 1, 'severity': 2},
            {'defect_id': 'D007', 'revision': 2, 'mileage_km': 7.0, 'lateral_mm': 1, 'severity': 2},
        ])
        self.assertEqual(response.status_code, 201)
        before = self._detail(dataset_id)
        conflict = self._supplement(dataset_id, [
            {'defect_id': 'D006', 'revision': 2, 'mileage_km': 66.0, 'lateral_mm': 1, 'severity': 2},
            {'defect_id': 'D777', 'revision': 1, 'mileage_km': 77.0, 'lateral_mm': 1, 'severity': 2},
        ])
        self.assertEqual(conflict.status_code, 409)
        after = self._detail(dataset_id)
        self.assertEqual(before['checksum'], after['checksum'])
        self.assertEqual(before['records'], after['records'])
        self.assertEqual(len(before['supplements']), len(after['supplements']))

    def test_intra_delivery_only_highest_revision_applies(self):
        dataset_id = self._dataset(self._rows())
        response = self._supplement(dataset_id, [
            {'defect_id': 'D800', 'revision': 1, 'mileage_km': 80.0, 'lateral_mm': 1, 'severity': 2},
            {'defect_id': 'D800', 'revision': 2, 'mileage_km': 81.0, 'lateral_mm': 1, 'severity': 3},
        ])
        supplement = response.json()['supplement']
        self.assertEqual((supplement['added'], supplement['ignored']), (1, 1))
        row = next(row for row in self._detail(dataset_id)['records'] if row['defect_id'] == 'D800')
        self.assertEqual(row['mileage_km'], 81.0)

    def test_experiment_created_before_supplement_uses_original_data(self):
        dataset_id = self._dataset(self._rows())
        job = self.client.post('/jobs', headers=self.auth['analyst'],
                               json={'name': '补发前试验 · ' + self._testMethodName, 'dataset_id': dataset_id,
                                     'params': {'eps_m': 100, 'min_points': 3}}).json()
        self._supplement(dataset_id, [{'defect_id': f'D{i:03}', 'revision': 5, 'revoked': True} for i in range(1, 8)])
        detail = self.client.get(f'/jobs/{job["id"]}', headers=self.auth['analyst']).json()
        self.assertEqual(detail['snapshot']['rows'], 15)
        with patch.object(worker, 'deliver', lambda *a, **k: None):
            worker.execute(job['id'])
        detail = self.client.get(f'/jobs/{job["id"]}', headers=self.auth['analyst']).json()
        self.assertEqual(detail['status'], 'completed')
        self.assertTrue(detail['result']['summary'].startswith('在15个缺陷点中'))

    def test_viewer_cannot_supplement(self):
        dataset_id = self._dataset(self._rows())
        response = self._supplement(dataset_id, [{'defect_id': 'D900', 'revision': 1, 'mileage_km': 90.0, 'lateral_mm': 1, 'severity': 2}], role='viewer')
        self.assertEqual(response.status_code, 403)

    def test_invalid_row_rejects_whole_delivery(self):
        dataset_id = self._dataset(self._rows())
        before = self._detail(dataset_id)
        response = self._supplement(dataset_id, [
            {'defect_id': 'D910', 'revision': 1, 'mileage_km': 91.0, 'lateral_mm': 1, 'severity': 2},
            {'defect_id': 'D911', 'revision': 1, 'mileage_km': -1, 'lateral_mm': 1, 'severity': 2},
        ])
        self.assertEqual(response.status_code, 422)
        self.assertEqual(before['checksum'], self._detail(dataset_id)['checksum'])


if __name__ == '__main__':
    unittest.main()
