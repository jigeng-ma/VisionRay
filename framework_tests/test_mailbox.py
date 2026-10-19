import sys
from pathlib import Path
import json
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
import socket
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from unittest.mock import patch
from unittest.mock import Mock
from studio.errors import TestBlocked
from studio.mailbox import VerificationMailbox, extract_code


class MailboxTests(unittest.TestCase):
    def test_daily_count_reads_headers_only(self):
        today = datetime.now(timezone(timedelta(hours=8))).strftime('%a, %d %b %Y %H:%M:%S +0800')
        box = Mock()
        box.uid.side_effect = [
            ('OK', [b'1']),
            ('OK', [(b'1', f'Date: {today}\r\nSubject: Code 123456\r\n\r\n'.encode())]),
        ]
        mailbox = VerificationMailbox.__new__(VerificationMailbox)
        mailbox._open = Mock(return_value=box)
        self.assertEqual(mailbox.today_code_count(), 1)
        self.assertEqual(box.uid.call_args.args[-1], '(BODY.PEEK[HEADER.FIELDS (DATE SUBJECT)])')
        box.logout.assert_called_once_with()

    def test_alternate_account_uses_its_own_imap_authorization(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / 'configs' / 'mail_private.json').read_text(encoding='utf-8'))
        account = next(iter(config['alternate_accounts']))
        mailbox = VerificationMailbox(root, account)
        self.assertEqual(mailbox.account, account)
        self.assertEqual(mailbox.authorization_code,
                         config['alternate_accounts'][account]['authorization_code'])

    def test_extract_code_uses_subject_or_body(self):
        message = EmailMessage()
        message['Subject'] = 'VisionRay verification: 123456'
        message.set_content('ignored 999')
        self.assertEqual(extract_code(message), '123456')

    def test_new_uids_exclude_codes_that_existed_before_checkpoint(self):
        self.assertEqual(VerificationMailbox._new_uids([101, 102, 105], 102), [105])

    def test_dns_failure_is_blocked(self):
        mailbox = VerificationMailbox.__new__(VerificationMailbox)
        mailbox.host, mailbox.port = 'imap.example.test', 993
        with patch('studio.mailbox.imaplib.IMAP4_SSL', side_effect=socket.gaierror(11001, 'getaddrinfo failed')):
            with self.assertRaisesRegex(TestBlocked, 'IMAP 服务不可达'):
                mailbox._open()


if __name__ == '__main__':
    unittest.main(verbosity=2)
