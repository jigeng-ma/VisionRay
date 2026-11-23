from unittest.mock import Mock

import pytest

from cases.g_series.test_g7_smoke_mixed_download import file_versions


@pytest.mark.parametrize('allow_missing,error,expected', [
    (True, "find: 'files/media': No such file or directory", {}),
    (False, "find: 'files/media': No such file or directory", None),
    (True, "find: 'files/media': Permission denied", None),
])
def test_missing_media_is_allowed_only_for_the_baseline(allow_missing, error, expected):
    failure = RuntimeError(error)
    adb = Mock()
    adb.shell.side_effect = failure
    if expected is None:
        with pytest.raises(RuntimeError) as caught:
            file_versions(adb, 'phone', 'app', allow_missing=allow_missing)
        assert caught.value is failure
    else:
        assert file_versions(adb, 'phone', 'app', allow_missing=allow_missing) == expected
