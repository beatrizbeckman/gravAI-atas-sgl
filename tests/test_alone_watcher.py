from gravai.recording.utils import AloneWatcher, page_says_alone


def test_leaves_after_being_alone_once_others_had_been_there():
    w = AloneWatcher(alone_seconds=120, empty_grace_seconds=900)
    assert w.update(alone=False, now=0) is False  # people in the call
    assert w.update(alone=True, now=10) is False  # everyone left
    assert w.update(alone=True, now=129) is False
    assert w.update(alone=True, now=130) is True


def test_someone_coming_back_resets_the_count():
    w = AloneWatcher(alone_seconds=120)
    w.update(alone=False, now=0)
    w.update(alone=True, now=10)
    w.update(alone=False, now=100)  # came back
    assert w.update(alone=True, now=200) is False
    assert w.update(alone=True, now=320) is True


def test_an_empty_meeting_gets_the_longer_grace_before_anyone_arrives():
    w = AloneWatcher(alone_seconds=120, empty_grace_seconds=900)
    assert w.update(alone=True, now=0) is False
    assert w.update(alone=True, now=600) is False  # still waiting for people
    assert w.update(alone=True, now=900) is True  # nobody came


def test_zero_disables_it():
    w = AloneWatcher(alone_seconds=0)
    w.update(alone=False, now=0)
    assert w.update(alone=True, now=10_000) is False


def test_alone_texts_in_english_and_portuguese():
    assert page_says_alone("Meeting\nWaiting for others to join...\nMore")
    assert page_says_alone("You\u2019re the only one here")
    assert page_says_alone("Aguardando outras pessoas ingressarem")
    assert not page_says_alone("Ana\nBruno\nShare\nLeave")
