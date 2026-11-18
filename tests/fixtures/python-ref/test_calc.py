from calc import add, clamp, is_positive


def test_add() -> None:
    assert add(2, 3) == 5
    assert add(-2, 2) == 0


def test_is_positive() -> None:
    assert is_positive(1)
    assert not is_positive(0)
    assert not is_positive(-1)


def test_clamp() -> None:
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(11, 0, 10) == 10
    assert clamp(0, 0, 10) == 0
    assert clamp(10, 0, 10) == 10
