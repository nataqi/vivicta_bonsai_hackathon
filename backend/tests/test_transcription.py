import unittest
from types import SimpleNamespace

from app.transcription import SpeakerTurnAssembler


def word(
    text: str,
    start: float,
    end: float,
    speaker: int | None,
    punctuated_word: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        word=text,
        punctuated_word=punctuated_word,
        start=start,
        end=end,
        speaker=speaker,
    )


def result(
    words: list[SimpleNamespace],
    *,
    is_final: bool = True,
    speech_final: bool = False,
    from_finalize: bool = False,
) -> SimpleNamespace:
    alternative = SimpleNamespace(
        transcript=" ".join(item.word for item in words),
        words=words,
    )
    return SimpleNamespace(
        is_final=is_final,
        speech_final=speech_final,
        from_finalize=from_finalize,
        channel=SimpleNamespace(alternatives=[alternative]),
    )


class SpeakerTurnAssemblerTests(unittest.TestCase):
    def test_ignores_interim_and_empty_results(self) -> None:
        assembler = SpeakerTurnAssembler()

        interim = result(
            [word("temporary", 0.0, 0.4, 0)],
            is_final=False,
            speech_final=True,
        )
        empty = result([], speech_final=True)

        self.assertEqual(assembler.consume(interim), [])
        self.assertEqual(assembler.consume(empty), [])

    def test_accumulates_final_segments_until_speech_final(self) -> None:
        assembler = SpeakerTurnAssembler()

        first = result([word("hello", 1.0, 1.4, 7, "Hello")])
        second = result(
            [word("there", 1.5, 2.0, 7, "there.")],
            speech_final=True,
        )

        self.assertEqual(assembler.consume(first), [])
        turns = assembler.consume(second)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["speaker"], "advisor")
        self.assertEqual(turns[0]["text"], "Hello there.")
        self.assertEqual(turns[0]["startTimeMs"], 1000)
        self.assertEqual(turns[0]["endTimeMs"], 2000)
        self.assertEqual(turns[0]["durationMs"], 1000)
        self.assertTrue(turns[0]["isFinal"])

    def test_splits_speaker_changes_and_keeps_mapping(self) -> None:
        assembler = SpeakerTurnAssembler()
        mixed = result(
            [
                word("I", 0.0, 0.2, 4),
                word("understand.", 0.2, 0.8, 4),
                word("Thanks.", 0.9, 1.4, 9),
            ],
            speech_final=True,
        )

        turns = assembler.consume(mixed)

        self.assertEqual([turn["speaker"] for turn in turns], ["advisor", "customer"])
        self.assertEqual([turn["text"] for turn in turns], ["I understand.", "Thanks."])

        later = result([word("Again.", 2.0, 2.5, 4)], speech_final=True)
        self.assertEqual(assembler.consume(later)[0]["speaker"], "advisor")

    def test_finalize_flushes_once(self) -> None:
        assembler = SpeakerTurnAssembler()
        finalized = result(
            [word("last", 0.0, 0.3, 0), word("phrase", 0.3, 0.7, 0)],
            from_finalize=True,
        )

        turns = assembler.consume(finalized)

        self.assertEqual(len(turns), 1)
        self.assertEqual(assembler.flush(), [])

    def test_new_session_has_fresh_speaker_mapping(self) -> None:
        first_session = SpeakerTurnAssembler()
        second_session = SpeakerTurnAssembler()

        first_turn = first_session.consume(
            result([word("one", 0.0, 0.2, 3)], speech_final=True)
        )[0]
        second_turn = second_session.consume(
            result([word("two", 0.0, 0.2, 8)], speech_final=True)
        )[0]

        self.assertEqual(first_turn["speaker"], "advisor")
        self.assertEqual(second_turn["speaker"], "advisor")


if __name__ == "__main__":
    unittest.main()
