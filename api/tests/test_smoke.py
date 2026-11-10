from lusiform_common import BaseAppSettings


def test_common_importable() -> None:
    assert BaseAppSettings().service_name
