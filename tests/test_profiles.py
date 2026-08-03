from paydaysuper.profiles import normalise_header


def test_normalise_header_folds_case_space_and_punctuation():
    assert normalise_header("  Employee   Membership #  ") == "employee membership"
    assert normalise_header("Paid Date") == "paid date"
    assert normalise_header("Employee Name") == "employee name"


def test_normalise_header_keeps_digits():
    assert normalise_header("Period 1 To") == "period 1 to"
