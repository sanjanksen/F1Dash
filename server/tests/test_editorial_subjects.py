from editorial.subjects import tag_subjects


def test_tag_subjects_detects_driver_surname():
    body = "Lando Norris stayed out a lap longer than Leclerc to extract clean air at Suzuka."
    rows = tag_subjects(article_id=1, body=body, title="Norris on the soft compound")
    refs = {(r["kind"], r["ref"]) for r in rows}
    assert ("driver", "NOR") in refs
    assert all(r["article_id"] == 1 for r in rows)


def test_tag_subjects_detects_team_name():
    body = "McLaren rolled out a revised floor and front wing for the Imola weekend."
    rows = tag_subjects(article_id=42, body=body)
    refs = {(r["kind"], r["ref"]) for r in rows}
    assert ("team", "mclaren") in refs


def test_tag_subjects_empty_when_no_f1_mentions():
    body = "The local football team is going through a tough patch and the manager is under pressure."
    rows = tag_subjects(article_id=7, body=body)
    assert rows == []
