import json
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


class SchemaDriftTests(unittest.TestCase):
    def test_observation_schema_accepts_current_sources(self):
        schema = json.loads((BASE / 'schemas' / 'observation.schema.json').read_text())
        sources = set(schema['properties']['source']['enum'])
        for source in ['hermes-sessions', 'correction-mining', 'openclaw-sessions', 'openclaw-semantic', 'promise-reality']:
            self.assertIn(source, sources)

    def test_intent_schema_accepts_current_adapters(self):
        schema = json.loads((BASE / 'schemas' / 'intent.schema.json').read_text())
        self.assertEqual(schema['properties']['id']['pattern'], r'^intent_[a-z0-9][a-z0-9_-]{0,120}$')
        adapters = set(schema['properties']['source_adapters']['items']['enum'])
        for adapter in ['HermesSessionAdapter', 'CorrectionMiningAdapter', 'OpenClawSessionAdapter', 'OpenClawSemanticAdapter', 'PromiseRealityAdapter']:
            self.assertIn(adapter, adapters)

    def test_approval_and_build_packet_schemas_share_runtime_safe_intent_pattern(self):
        for name, key in [('approval.schema.json', 'intent_id'), ('build_packet.schema.json', 'intent_id')]:
            schema = json.loads((BASE / 'schemas' / name).read_text())
            self.assertEqual(schema['properties'][key]['pattern'], r'^intent_[a-z0-9][a-z0-9_-]{0,120}$')

    def test_room_summary_schema_requires_blocked_ready_lane(self):
        schema = json.loads((BASE / 'schemas' / 'room_summary.schema.json').read_text())
        self.assertIn('blocked_ready', schema['properties']['lanes']['required'])


if __name__ == '__main__':
    unittest.main()
