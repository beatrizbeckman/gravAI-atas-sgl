import json

from gravai.minutes.transcript_normalizer import load_session_segments, normalize_segments


def seg(start, end, text, no_speech_prob=0.0):
    return {"start": start, "end": end, "text": text, "no_speech_prob": no_speech_prob}


def test_orders_across_speakers_and_merges_short_pauses():
    result = normalize_segments(
        {
            "Ana": [seg(0.0, 2.0, " Bom dia,"), seg(2.5, 4.0, "vamos começar.")],
            "Bruno": [seg(4.5, 6.0, " Ok."), seg(1.0, 1.5, "  ")],
        }
    )
    assert [(u.speaker, u.start, u.end, u.text) for u in result] == [
        ("Ana", 0.0, 4.0, "Bom dia, vamos começar."),
        ("Bruno", 4.5, 6.0, "Ok."),
    ]


def test_does_not_merge_when_someone_speaks_in_between():
    result = normalize_segments(
        {
            "Ana": [seg(0.0, 1.0, "Primeiro"), seg(1.5, 2.0, "terceiro")],
            "Bruno": [seg(1.0, 1.4, "segundo")],
        }
    )
    assert [u.text for u in result] == ["Primeiro", "segundo", "terceiro"]


def test_drops_probable_silence_and_bad_timestamps():
    result = normalize_segments(
        {
            "Ana": [
                seg(0.0, 1.0, "Legendas pela comunidade", no_speech_prob=0.95),
                seg(3.0, 3.0, "x"),
                seg(5.0, 6.0, "fala real"),
            ],
        }
    )
    assert [u.text for u in result] == ["fala real"]


def test_resolves_container_paths_against_tracks_dir(tmp_path):
    (tmp_path / "track_speaking-element-aaa_transcription_segments.json").write_text(
        json.dumps([seg(0, 1, "oi")]), encoding="utf-8"
    )
    (tmp_path / "session_transcription.json").write_text(
        json.dumps(
            {
                "tracks": {
                    "speaking-element-aaa": {
                        "participant_name": "Ana",
                        "transcription": {
                            "transcription_segments_file_path": "/app/tmp/x_tracks/track_speaking-element-aaa_transcription_segments.json"
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert load_session_segments(str(tmp_path)) == {"Ana": [seg(0, 1, "oi")]}


def test_drops_known_hallucinations_and_loops():
    result = normalize_segments(
        {
            "Ana": [
                seg(0.0, 1.0, "Legendas pela comunidade Amara.org"),
                seg(2.0, 3.0, "[Música]"),
                seg(4.0, 5.0, "..."),
                seg(6.0, 7.0, " Legenda Adriana Zanotto"),
                seg(10.0, 11.0, "Obrigado."),
                seg(11.0, 12.0, "Obrigado."),
                seg(12.0, 13.0, "Obrigado."),
                seg(20.0, 21.0, "fala real"),
            ],
        },
        merge_gap_s=None,
    )
    assert [u.text for u in result] == ["Obrigado.", "fala real"]


def test_keeps_one_copy_of_speech_heard_on_two_tracks():
    result = normalize_segments(
        {
            "Ana": [seg(10.0, 14.0, "Então a entrega fica pra sexta-feira.")],
            "Bruno": [seg(11.5, 13.0, "a entrega fica pra sexta"), seg(14.2, 15.0, "Beleza.")],
        }
    )
    assert [(u.speaker, u.text) for u in result] == [
        ("Ana", "Então a entrega fica pra sexta-feira."),
        ("Bruno", "Beleza."),
    ]


def test_different_speech_at_the_same_time_is_kept():
    result = normalize_segments(
        {
            "Ana": [seg(0.0, 2.0, "Eu acho que sim.")],
            "Bruno": [seg(0.5, 2.0, "Não concordo.")],
        }
    )
    assert [u.speaker for u in result] == ["Ana", "Bruno"]


def test_speech_that_mentions_subtitles_is_kept():
    result = normalize_segments(
        {"Ana": [seg(0.0, 4.0, "A legenda do gráfico precisa ser revisada antes da entrega.")]},
        merge_gap_s=None,
    )
    assert len(result) == 1
