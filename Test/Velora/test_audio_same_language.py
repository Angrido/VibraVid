# 21.11.26
# ruff: noqa: E402

"""Two selected audios of one language (AAC + AC-3, en-US + en-GB, two tags of one locale) each get their own task key,
temp folder and output file, and the mux still names each with its own language."""

import sys
import threading
from pathlib import Path

workspace_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(workspace_root))

from VibraVid.core.manifest.stream import Stream
from VibraVid.core.utils.language import track_title_and_iso_lang
from VibraVid.core.velora.downloader import MediaDownloader


def _audio(lang, resolved="", codecs="mp4a.40.2"):
    return Stream(type="audio", format="hls", language=lang, resolved_language=resolved, codecs=codecs, selected=True)


def _downloader(tmp_path, streams):
    dl = object.__new__(MediaDownloader)
    dl.streams = streams
    dl.output_dir = tmp_path
    dl._tmp_dir = tmp_path
    dl.filename = "movie"
    dl.key = None
    dl.download_id = None
    dl._assigned_sub_names = set()
    dl._assigned_sub_lock = threading.Lock()
    dl._track_done_events = {}
    dl._track_results = {}
    dl._track_done_lock = threading.Lock()
    dl._prepare_labels()
    return dl


def _names(dl, stream):
    return dl._stream_task_key(stream), dl._make_stream_dir(stream, "hls").name, dl._out_filename(stream, "mp4")


def test_a_single_audio_keeps_todays_names(tmp_path):
    aac = _audio("en")
    dl = _downloader(tmp_path, [aac])

    assert _names(dl, aac) == ("aud_en", "a_en", "movie.en.m4a")


def test_two_codecs_of_one_language_do_not_share_names(tmp_path):
    aac, ac3 = _audio("en"), _audio("en", codecs="ac-3")
    dl = _downloader(tmp_path, [aac, ac3])

    assert _names(dl, aac) == ("aud_en", "a_en", "movie.en.m4a")
    first, second = _names(dl, aac), _names(dl, ac3)
    assert all(a != b for a, b in zip(first, second, strict=True))
    assert [key for key, _label in dl._get_prebuilt_tasks()] == [first[0], second[0]]


def test_regional_variants_keep_their_own_track_result(tmp_path):
    spain, latam = _audio("es-ES", "es-ES"), _audio("es-419", "es-419")
    dl = _downloader(tmp_path, [spain, latam])

    dl._record_track_done(dl._stream_task_key(spain), tmp_path / "es-es.m4a")
    dl._record_track_done(dl._stream_task_key(latam), tmp_path / "es-419.m4a")

    assert dl._get_track_result(dl._stream_task_key(spain)) == tmp_path / "es-es.m4a"
    assert dl._get_track_result(dl._stream_task_key(latam)) == tmp_path / "es-419.m4a"


def test_two_tags_of_one_locale_get_two_files_each_named_by_its_language(tmp_path):
    first, second = _audio("en", "en"), _audio("eng", "en")
    dl = _downloader(tmp_path, [first, second])

    files = [dl._out_filename(s, "mp4") for s in (first, second)]
    assert len(set(files)) == 2
    for name in files:
        (tmp_path / name).write_bytes(b"a")

    audios = dl._build_status([])["audios"]
    assert sorted(Path(a["path"]).name for a in audios) == sorted(files)
    assert [track_title_and_iso_lang(a) for a in audios] == [("English", "eng"), ("English", "eng")]
    assert {a["language_iso2"] for a in audios} == {"en"}


def test_mkvmerge_names_the_second_audio_by_its_language(tmp_path):
    from VibraVid.core.muxing.merge import _mkvmerge_lang_flag

    first, second = _audio("es-419", "es-419"), _audio("es-419", "es-419", codecs="ac-3")
    dl = _downloader(tmp_path, [first, second])
    for s in (first, second):
        (tmp_path / dl._out_filename(s, "mp4")).write_bytes(b"a")

    assert [_mkvmerge_lang_flag(a) for a in dl._build_status([])["audios"]] == ["es-419", "es-419"]


def test_the_mux_keeps_the_manifest_order_of_one_language(tmp_path):
    # Plain name order would put "movie.en.2.m4a" (AC-3) before "movie.en.m4a" (AAC) and make it the default audio
    aac, ac3, ita = _audio("en"), _audio("en", codecs="ac-3"), _audio("it")
    dl = _downloader(tmp_path, [aac, ac3, ita])
    for s in (aac, ac3, ita):
        (tmp_path / dl._out_filename(s, "mp4")).write_bytes(b"a")

    names = [Path(a["path"]).name for a in dl._build_status([])["audios"]]
    assert names == ["movie.en.m4a", "movie.en.2.m4a", "movie.it.m4a"]


def test_task_keys_do_not_depend_on_prepare_labels(tmp_path):
    # The generic downloader's pipe mux asks for the audio task keys before _prepare_labels runs
    aac, ac3 = _audio("en"), _audio("en", codecs="ac-3")
    dl = object.__new__(MediaDownloader)
    dl.streams = [aac, ac3]

    assert [dl._stream_task_key(s) for s in (aac, ac3)] == ["aud_en", "aud_en_2"]
