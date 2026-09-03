import pytest
from fastapi import HTTPException


def test_safe_path_inside_root(main_module, roots):
    p = main_module.safe_path("audio", "house/deep/track.mp3")
    assert p == (roots["audio"] / "house/deep/track.mp3").resolve()


def test_safe_path_root_itself(main_module, roots):
    assert main_module.safe_path("audio", "") == roots["audio"].resolve()
    assert main_module.safe_path("audio", "/") == roots["audio"].resolve()


@pytest.mark.parametrize("rel", ["../x", "house/../../x", "/../x", "..", "house/../.."])
def test_safe_path_blocks_traversal(main_module, roots, rel):
    with pytest.raises(HTTPException) as e:
        main_module.safe_path("audio", rel)
    assert e.value.status_code == 400


def test_safe_path_bad_root(main_module, roots):
    with pytest.raises(HTTPException) as e:
        main_module.safe_path("nope", "x")
    assert e.value.status_code == 400


def test_slugify(main_module):
    assert main_module.slugify("Deep House!!") == "deep-house"
    assert main_module.slugify("  Drum & Bass ") == "drum-bass"
    assert main_module.slugify("") == "untitled"
    assert main_module.slugify("!!!", "general") == "general"


def test_safe_filename(main_module):
    assert main_module.safe_filename("Daft Punk / Around: The World") == "Daft Punk Around The World"
    assert main_module.safe_filename("") == "untitled"
    assert main_module.safe_filename("///", "Unknown") == "Unknown"


def test_unique_path(main_module, tmp_path):
    first = main_module.unique_path(tmp_path, "a", "mp3")
    assert first == tmp_path / "a.mp3"
    first.write_bytes(b"")
    assert main_module.unique_path(tmp_path, "a", "mp3") == tmp_path / "a (1).mp3"


@pytest.mark.parametrize(
    "url,vid",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?list=PL1&v=dQw4w9WgXcQ&t=5", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://example.com/", None),
        ("", None),
    ],
)
def test_extract_video_id(main_module, url, vid):
    assert main_module.extract_video_id(url) == vid
