"""163 邮箱验证码读取。仅接受本次请求快照之后到达的邮件。"""
import email
from email import policy
import imaplib
import json
import re
import time
from pathlib import Path
from .errors import TestBlocked


CODE = re.compile(r'(?<!\d)(\d{4,8})(?!\d)')


class MailboxUnavailable(TestBlocked):
    """邮箱网络不可达，属于外部前置条件而非用例失败。"""


def extract_code(message):
    """从主题和正文提取首个 4 至 8 位验证码。"""
    text = f"{message.get('Subject', '')}\n"
    parts = (p for p in message.walk() if p.get_content_type() == 'text/plain') if message.is_multipart() else (message,)
    for part in parts:
        try:
            text += '\n' + part.get_content()
        except (LookupError, UnicodeDecodeError):
            continue
    found = CODE.search(text)
    return found.group(1) if found else None


class VerificationMailbox:
    def __init__(self, root):
        config = json.loads((Path(root) / 'configs' / 'mail_private.json').read_text(encoding='utf-8'))
        self.host = config['imap_host']
        self.port = int(config.get('imap_port', 993))
        self.account = config['account']
        self.authorization_code = config['authorization_code']

    def _open(self):
        try:
            box = imaplib.IMAP4_SSL(self.host, self.port, timeout=20)
        except OSError as exc:
            raise MailboxUnavailable(f'邮箱 IMAP 服务不可达：{exc}') from exc
        box.login(self.account, self.authorization_code)
        status, detail = box.xatom('ID', '(\"name\" \"VisionRay\" \"version\" \"1.0\" \"vendor\" \"DPVR QA\" \"support-email\" \"test_zsb@163.com\")')
        if status != 'OK':
            box.logout()
            raise RuntimeError('IMAP ID 注册失败：' + b' '.join(detail).decode('utf-8', 'replace'))
        status, detail = box.select('INBOX', readonly=True)
        if status != 'OK':
            box.logout()
            reason = b' '.join(detail).decode('utf-8', 'replace')
            raise RuntimeError('无法打开收件箱：' + reason)
        return box

    @staticmethod
    def _uids(box):
        status, data = box.uid('search', None, 'ALL')
        if status != 'OK':
            raise RuntimeError('无法查询收件箱。')
        return [int(uid) for uid in data[0].split()]

    @staticmethod
    def _new_uids(uids, floor):
        return [uid for uid in uids if uid > floor]

    def checkpoint(self):
        """在触发发送验证码前调用，返回邮箱 UID 水位线。"""
        box = self._open()
        try:
            uids = self._uids(box)
            return {'uid': uids[-1] if uids else 0, 'created_at': time.time()}
        finally:
            box.logout()

    def wait_for_code(self, checkpoint, timeout=90, interval=3, sender=None, subject=None):
        """只检查 UID 大于请求前水位线的邮件，避免读取旧验证码。"""
        floor = int(checkpoint['uid'])
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            box = self._open()
            try:
                for uid in reversed(self._new_uids(self._uids(box), floor)):
                    status, data = box.uid('fetch', str(uid), '(BODY.PEEK[])')
                    if status != 'OK' or not data or not data[0]:
                        continue
                    message = email.message_from_bytes(data[0][1], policy=policy.default)
                    if sender and sender.lower() not in str(message.get('From', '')).lower():
                        continue
                    if subject and subject.lower() not in str(message.get('Subject', '')).lower():
                        continue
                    code = extract_code(message)
                    if code:
                        return {'code': code, 'uid': uid, 'subject': str(message.get('Subject', ''))}
            finally:
                box.logout()
            time.sleep(interval)
        raise TimeoutError(f'等待新验证码超时（{timeout} 秒）；本次仅接受 UID 大于 {floor} 的邮件。')
