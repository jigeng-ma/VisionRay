import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
import socket
from email.message import EmailMessage
from unittest.mock import patch
from studio.errors import TestBlocked
from studio.mailbox import VerificationMailbox, extract_code


class MailboxTests(unittest.TestCase):
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
