from score2ly.cli import main


def test_main_no_args(capsys):
    import sys
    sys.argv = ["score2ly"]
    try:
        main()
    except SystemExit as e:
        assert e.code == 0