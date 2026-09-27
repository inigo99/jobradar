"""robots.txt matching with wildcards, as the sites JobRadar reads write it."""

from jobradar.sources.robots import RobotRules

UA = "JobRadar/1.0 (+https://github.com/inigo99/jobradar) personal job-search assistant"


def test_wildcards_in_the_middle_are_honoured():
    # France Travail and Net-Empregos, trimmed: search pages are off limits.
    france = RobotRules("User-agent: *\nDisallow: *motsCles=*\nDisallow: /espacepersonnel/\n")
    assert not france.can_fetch(UA, "https://candidat.francetravail.fr/offres/recherche?motsCles=infirmier")
    assert france.can_fetch(UA, "https://candidat.francetravail.fr/offres/emploi/infirmier/s36m2")
    portugal = RobotRules("User-agent: *\nAllow: /\nDisallow: /*?*chaves=\n")
    assert not portugal.can_fetch(UA, "https://www.net-empregos.com/pesquisa-empregos.asp?chaves=enfermeiro")
    assert portugal.can_fetch(UA, "https://www.net-empregos.com/rss.asp")


def test_longest_rule_wins_and_allow_breaks_ties():
    rules = RobotRules("User-agent: *\nDisallow: /jobs/\nAllow: /jobs/public/\nDisallow: /x\nAllow: /x\n")
    assert not rules.can_fetch(UA, "https://a.example/jobs/42")
    assert rules.can_fetch(UA, "https://a.example/jobs/public/42")
    assert rules.can_fetch(UA, "https://a.example/x")


def test_end_anchor_and_empty_rules():
    rules = RobotRules("User-agent: *\nDisallow: /*.pdf$\nDisallow:\n")
    assert not rules.can_fetch(UA, "https://a.example/cv.pdf")
    assert rules.can_fetch(UA, "https://a.example/cv.pdf?download=1")
    assert RobotRules("").can_fetch(UA, "https://a.example/anything")


def test_a_group_naming_the_agent_replaces_the_general_one():
    rules = RobotRules("User-agent: *\nDisallow: /\n\nUser-agent: jobradar\nAllow: /\n")
    assert rules.can_fetch(UA, "https://a.example/jobs")
    other = RobotRules("User-agent: Yandex\nDisallow: /\n\nUser-agent: *\nDisallow: /login\n")
    assert other.can_fetch(UA, "https://a.example/jobs")
    assert not other.can_fetch(UA, "https://a.example/login")
