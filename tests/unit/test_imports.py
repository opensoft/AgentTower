from importlib.metadata import PackageNotFoundError, version as _version

from agenttower import __version__


def test_agenttower_imports() -> None:
    assert isinstance(__version__, str)
    assert __version__

    try:
        installed = _version("agenttower")
    except PackageNotFoundError:
        assert __version__ == "0.0.0+local"
    else:
        assert __version__ == installed
