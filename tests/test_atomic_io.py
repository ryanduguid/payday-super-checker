import pytest

from paydaysuper.atomic_io import atomic_text_output


def test_atomic_text_output_keeps_the_previous_file_when_writing_fails(tmp_path):
    """A partially written payroll report must never replace the last complete one."""
    output = tmp_path / "report.csv"
    output.write_text("previous complete report\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="simulated failure"):
        with atomic_text_output(output, encoding="utf-8") as stream:
            stream.write("partial replacement\n")
            raise RuntimeError("simulated failure")

    assert output.read_text(encoding="utf-8") == "previous complete report\n"
    assert not list(tmp_path.glob(".payday-super-checker-*.tmp"))


def test_generated_output_requires_an_explicit_csv_filename(tmp_path):
    with pytest.raises(ValueError, match=r"must use a \.csv filename"):
        with atomic_text_output(tmp_path / "existing-report.txt", encoding="utf-8"):
            pytest.fail("validation must happen before opening a staging file")

    assert not list(tmp_path.glob(".payday-super-checker-*.tmp"))
