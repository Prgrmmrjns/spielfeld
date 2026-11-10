from pipeline.team_map import slug_from_fd, slug_from_ol


def test_fd_known_teams():
    assert slug_from_fd("Bayern Munich") == "bayern"
    assert slug_from_fd("M'gladbach") == "gladbach"
    assert slug_from_fd("St Pauli") == "stpauli"


def test_ol_known_teams():
    assert slug_from_ol({"teamName": "FC Bayern München", "shortName": "Bayern"}) == "bayern"
    assert slug_from_ol("Borussia Mönchengladbach") == "gladbach"
