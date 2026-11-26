"""Regression test for ECC-026 (BA-014): <lambda>/<listcomp>, dotted/custom exceptions, chained blocks."""

from bugarena.discovery.log_parser import parse_python_traceback


def test_ecc_026_lambda_trailing_colon_dotted_and_chained_tracebacks():
    tb = (
        "Traceback (most recent call last):\n"
        '  File "src/inner.py", line 10, in <listcomp>\n'
        "    x = [int(v) for v in items]\n"
        "json.decoder.JSONDecodeError: Expecting value: line 1 column 1\n"
        "\n"
        "The above exception was the direct cause of the following exception:\n"
        "\n"
        "Traceback (most recent call last):\n"
        '  File "src/outer.py", line 25, in <lambda>\n'
        "    fn = lambda a: bad(a)\n"
        "my_mod.ValidationFailure: outer failed\n"
        "log_ts: 12:34:56 trailing colon note\n"
    )
    traces = parse_python_traceback(tb)
    assert len(traces) == 2
    assert traces[0].function_name == "<listcomp>"
    assert traces[0].error_message.startswith("json.decoder.JSONDecodeError:")
    assert traces[1].function_name == "<lambda>"
    assert traces[1].error_message == "my_mod.ValidationFailure: outer failed"
