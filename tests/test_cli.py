"""The command-line surface: the new commands are wired up."""

from jobradar.cli import _scrapling_browsers_installed, build_parser


def test_filtered_command_is_registered():
    args = build_parser().parse_args(["filtered", "--restore", "test:1"])
    assert args.func.__name__ == "cmd_filtered"
    assert args.restore == "test:1"


def test_filtered_defaults_to_listing():
    args = build_parser().parse_args(["filtered"])
    assert args.restore is None
    assert args.clear is False


def test_scrapling_browsers_installed_reads_the_marker_file(monkeypatch, tmp_path):
    import scrapling

    marker = tmp_path / ".scrapling_dependencies_installed"
    monkeypatch.setattr(scrapling, "__file__", str(tmp_path / "__init__.py"))
    assert _scrapling_browsers_installed() is False

    marker.touch()
    assert _scrapling_browsers_installed() is True


def test_scrapling_browsers_installed_false_without_scrapling(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "scrapling":
            raise ImportError("no scrapling")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert _scrapling_browsers_installed() is False
