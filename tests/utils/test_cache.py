from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any
from typing import TypeVar
from typing import Union
from unittest.mock import Mock

import pytest

from cachy import CacheManager
from packaging.tags import Tag
from poetry.core.packages.utils.link import Link

from poetry.utils.cache import ArtifactCache
from poetry.utils.cache import FileCache
from poetry.utils.env import MockEnv


if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch
    from pytest import FixtureRequest
    from pytest_mock import MockerFixture

    from tests.conftest import Config
    from tests.types import FixtureDirGetter


FILE_CACHE = Union[FileCache, CacheManager]
T = TypeVar("T")


@pytest.fixture
def repository_cache_dir(monkeypatch: MonkeyPatch, config: Config) -> Path:
    return config.repository_cache_directory


def patch_cachy(cache: CacheManager) -> CacheManager:
    old_put = cache.put
    old_remember = cache.remember

    def new_put(key: str, value: Any, minutes: int | None = None) -> Any:
        if minutes is not None:
            return old_put(key, value, minutes=minutes)
        else:
            return cache.forever(key, value)

    cache.put = new_put

    def new_remember(key: str, value: Any, minutes: int | None = None) -> Any:
        if minutes is not None:
            return old_remember(key, value, minutes=minutes)
        else:
            return cache.remember_forever(key, value)

    cache.remember = new_remember
    return cache


@pytest.fixture
def cachy_file_cache(repository_cache_dir: Path) -> CacheManager:
    cache = CacheManager(
        {
            "default": "cache",
            "serializer": "json",
            "stores": {
                "cache": {"driver": "file", "path": str(repository_cache_dir / "cache")}
            },
        }
    )
    return patch_cachy(cache)


@pytest.fixture
def poetry_file_cache(repository_cache_dir: Path) -> FileCache[T]:
    return FileCache(repository_cache_dir / "cache")


@pytest.fixture
def cachy_dict_cache() -> CacheManager:
    cache = CacheManager(
        {
            "default": "cache",
            "serializer": "json",
            "stores": {"cache": {"driver": "dict"}},
        }
    )
    return patch_cachy(cache)


def test_cache_validates(repository_cache_dir: Path) -> None:
    with pytest.raises(ValueError) as e:
        FileCache(repository_cache_dir / "cache", hash_type="unknown")
    assert str(e.value) == "FileCache.hash_type is unknown value: 'unknown'."


@pytest.mark.parametrize("cache_name", ["cachy_file_cache", "poetry_file_cache"])
def test_cache_get_put_has(cache_name: str, request: FixtureRequest) -> None:
    cache = request.getfixturevalue(cache_name)
    cache.put("key1", "value")
    cache.put("key2", {"a": ["json-encoded", "value"]})

    assert cache.get("key1") == "value"
    assert cache.get("key2") == {"a": ["json-encoded", "value"]}
    assert cache.has("key1")
    assert cache.has("key2")
    assert not cache.has("key3")


@pytest.mark.parametrize("cache_name", ["cachy_file_cache", "poetry_file_cache"])
def test_cache_forget(cache_name: str, request: FixtureRequest) -> None:
    cache = request.getfixturevalue(cache_name)
    cache.put("key1", "value")
    cache.put("key2", "value")

    assert cache.has("key1")
    assert cache.has("key2")

    cache.forget("key1")

    assert not cache.has("key1")
    assert cache.has("key2")


@pytest.mark.parametrize("cache_name", ["cachy_file_cache", "poetry_file_cache"])
def test_cache_flush(cache_name: str, request: FixtureRequest) -> None:
    cache = request.getfixturevalue(cache_name)
    cache.put("key1", "value")
    cache.put("key2", "value")

    assert cache.has("key1")
    assert cache.has("key2")

    cache.flush()

    assert not cache.has("key1")
    assert not cache.has("key2")


@pytest.mark.parametrize("cache_name", ["cachy_file_cache", "poetry_file_cache"])
def test_cache_remember(
    cache_name: str, request: FixtureRequest, mocker: MockerFixture
) -> None:
    cache = request.getfixturevalue(cache_name)

    method = Mock(return_value="value2")
    cache.put("key1", "value1")
    assert cache.remember("key1", method) == "value1"
    method.assert_not_called()

    assert cache.remember("key2", method) == "value2"
    method.assert_called()


@pytest.mark.parametrize("cache_name", ["cachy_file_cache", "poetry_file_cache"])
def test_cache_get_limited_minutes(
    mocker: MockerFixture,
    cache_name: str,
    request: FixtureRequest,
) -> None:
    cache = request.getfixturevalue(cache_name)

    # needs to be 10 digits because cachy assumes it's a 10-digit int.
    start_time = 1111111111

    mocker.patch("time.time", return_value=start_time)
    cache.put("key1", "value", minutes=5)
    cache.put("key2", "value", minutes=5)

    assert cache.get("key1") is not None
    assert cache.get("key2") is not None

    mocker.patch("time.time", return_value=start_time + 5 * 60 + 1)
    # check to make sure that the cache deletes for has() and get()
    assert not cache.has("key1")
    assert cache.get("key2") is None


def test_cachy_compatibility(
    cachy_file_cache: CacheManager, poetry_file_cache: FileCache[T]
) -> None:
    """
    The new file cache should be able to support reading legacy caches.
    """
    test_str = "value"
    test_obj = {"a": ["json", "object"]}
    cachy_file_cache.put("key1", test_str)
    cachy_file_cache.put("key2", test_obj)

    assert poetry_file_cache.get("key1") == test_str
    assert poetry_file_cache.get("key2") == test_obj

    poetry_file_cache.put("key3", test_str)
    poetry_file_cache.put("key4", test_obj)

    assert cachy_file_cache.get("key3") == test_str
    assert cachy_file_cache.get("key4") == test_obj


def test_get_cache_directory_for_link(tmp_path: Path) -> None:
    cache = ArtifactCache(cache_dir=tmp_path)
    directory = cache.get_cache_directory_for_link(
        Link("https://files.python-poetry.org/poetry-1.1.0.tar.gz")
    )

    expected = Path(
        f"{tmp_path.as_posix()}/11/4f/a8/"
        "1c89d75547e4967082d30a28360401c82c83b964ddacee292201bf85f2"
    )

    assert directory == expected


def test_get_cached_archives_for_link(
    fixture_dir: FixtureDirGetter, mocker: MockerFixture
) -> None:
    distributions = fixture_dir("distributions")
    cache = ArtifactCache(cache_dir=Path())

    mocker.patch.object(
        cache,
        "get_cache_directory_for_link",
        return_value=distributions,
    )
    archives = cache._get_cached_archives_for_link(
        Link("https://files.python-poetry.org/demo-0.1.0.tar.gz")
    )

    assert archives
    assert set(archives) == set(distributions.glob("demo-0.1.*"))


@pytest.mark.parametrize(
    ("link", "strict", "available_packages"),
    [
        (
            "https://files.python-poetry.org/demo-0.1.0.tar.gz",
            True,
            [
                Path("/cache/demo-0.1.0-py2.py3-none-any"),
                Path("/cache/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl"),
                Path("/cache/demo-0.1.0-cp37-cp37-macosx_10_15_x86_64.whl"),
            ],
        ),
        (
            "https://example.com/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl",
            False,
            [],
        ),
    ],
)
def test_get_not_found_cached_archive_for_link(
    mocker: MockerFixture,
    link: str,
    strict: bool,
    available_packages: list[Path],
) -> None:
    env = MockEnv(
        version_info=(3, 8, 3),
        marker_env={"interpreter_name": "cpython", "interpreter_version": "3.8.3"},
        supported_tags=[
            Tag("cp38", "cp38", "macosx_10_15_x86_64"),
            Tag("py3", "none", "any"),
        ],
    )
    cache = ArtifactCache(cache_dir=Path())

    mocker.patch.object(
        cache,
        "_get_cached_archives_for_link",
        return_value=available_packages,
    )

    archive = cache.get_cached_archive_for_link(Link(link), strict=strict, env=env)

    assert archive is None


@pytest.mark.parametrize(
    ("link", "cached", "strict"),
    [
        (
            "https://files.python-poetry.org/demo-0.1.0.tar.gz",
            "/cache/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl",
            False,
        ),
        (
            "https://example.com/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl",
            "/cache/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl",
            False,
        ),
        (
            "https://files.python-poetry.org/demo-0.1.0.tar.gz",
            "/cache/demo-0.1.0.tar.gz",
            True,
        ),
        (
            "https://example.com/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl",
            "/cache/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl",
            True,
        ),
    ],
)
def test_get_found_cached_archive_for_link(
    mocker: MockerFixture,
    link: str,
    cached: str,
    strict: bool,
) -> None:
    env = MockEnv(
        version_info=(3, 8, 3),
        marker_env={"interpreter_name": "cpython", "interpreter_version": "3.8.3"},
        supported_tags=[
            Tag("cp38", "cp38", "macosx_10_15_x86_64"),
            Tag("py3", "none", "any"),
        ],
    )
    cache = ArtifactCache(cache_dir=Path())

    mocker.patch.object(
        cache,
        "_get_cached_archives_for_link",
        return_value=[
            Path("/cache/demo-0.1.0-py2.py3-none-any"),
            Path("/cache/demo-0.1.0.tar.gz"),
            Path("/cache/demo-0.1.0-cp38-cp38-macosx_10_15_x86_64.whl"),
            Path("/cache/demo-0.1.0-cp37-cp37-macosx_10_15_x86_64.whl"),
        ],
    )

    archive = cache.get_cached_archive_for_link(Link(link), strict=strict, env=env)

    assert Path(cached) == archive
