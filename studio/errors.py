"""可恢复的环境或前提阻塞，不作为断言失败或通过。"""
class TestBlocked(RuntimeError):
    __test__ = False


class WaitTimeout(AssertionError):
    pass
