import json, os, re, tempfile, unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from subc_common import redact
from subc_publish_pending import reply_markup_for, format_message

ROOT = Path(__file__).resolve().parents[1]

class PublicSafetyTests(unittest.TestCase):
    def test_redaction_masks_common_tokens(self):
        gh_token = 'gh' + 'p_' + 'abcdefghijklmnopqrstuvwxyz123456'
        sk_token = 'sk-' + 'testsecret1234567890'
        text = f'token={gh_token} and api_key={sk_token}'
        out = redact(text)
        self.assertNotIn('ghp_', out)
        self.assertNotIn('sk-testsecret', out)
        self.assertIn('<REDACTED>', out)

    def test_no_private_chip_identifiers_in_repo(self):
        # Build private needles without writing them literally in the public template.
        needles = [
            '617' + '744' + '661',
            '-' + '100' + '397' + '144' + '8755',
            '138' + '.201' + '.30' + '.209',
            'hermes' + '.evgyur' + '.vip',
        ]
        token_regexes = [
            re.compile(r'gsk_[A-Za-z0-9_-]{20,}'),
            re.compile(r'pplx-[A-Za-z0-9_-]{20,}'),
            re.compile(r'gh[pousr]_[A-Za-z0-9_-]{20,}'),
        ]
        offenders=[]
        for p in ROOT.rglob('*'):
            if p.is_file() and '.git' not in p.parts and p.suffix not in {'.pyc'}:
                s=p.read_text(errors='ignore')
                for n in needles:
                    if n in s:
                        offenders.append((str(p.relative_to(ROOT)), n))
                for rx in token_regexes:
                    if rx.search(s):
                        offenders.append((str(p.relative_to(ROOT)), rx.pattern))
        self.assertEqual(offenders, [])

    def test_pending_card_has_buttons_contract(self):
        state={'posted':{},'tokens':{}}
        markup=reply_markup_for('intent_demo', state)
        row=markup['inline_keyboard'][0]
        self.assertEqual(row[0]['text'], '✅ Да')
        self.assertEqual(row[1]['text'], '❌ Нет')
        self.assertTrue(row[0]['callback_data'].startswith('subc:y:'))
        self.assertTrue(row[1]['callback_data'].startswith('subc:n:'))

    def test_message_does_not_include_source_path(self):
        msg=format_message('intent_demo', 'title: "Demo"\nproblem: "Problem"\nsuggested_build: "Build"\nconfidence: 0.5\n')
        self.assertNotIn('source:', msg)
