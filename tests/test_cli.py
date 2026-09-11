"""The command-line surface: the new commands are wired up."""

from jobradar.cli import build_parser


def test_filtered_command_is_registered():
    args = build_parser().parse_args(["filtered", "--restore", "test:1"])
    assert args.func.__name__ == "cmd_filtered"
    assert args.restore == "test:1"


def test_filtered_defaults_to_listing():
    args = build_parser().parse_args(["filtered"])
    assert args.restore is None
    assert args.clear is False
