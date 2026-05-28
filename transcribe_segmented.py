"""Segmented faster-whisper transcription for long audio.

Splits audio into fixed-length segments, transcribes each with CUDA (or CPU),
and merges the output with global-timeline timestamps.

Why segmentation: feeding a 30+ minute audio to faster-whisper in one call
can exceed VRAM on GPUs with ≤6 GB, causing CUDA driver-level crashes.
300-second segments keep the encoder-decoder cross-attention tensors small
enough to stay within budget while still providing enough context per chunk.
"""

import os
import time
import wave


def _read_audio_params(wav_path):
    wf = wave.open(wav_path, "rb")
    sample_rate = wf.getframerate()
    nchannels = wf.getnchannels()
    sampwidth = wf.getsampwidth()
    total_frames = wf.getnframes()
    wf.close()
    return sample_rate, nchannels, sampwidth, total_frames


def _write_segment(wav_path, start_frame, nframes, nchannels, sampwidth, sample_rate, seg_path):
    wf = wave.open(wav_path, "rb")
    wf.setpos(start_frame)
    raw = wf.readframes(nframes)
    wf.close()

    sw = wave.open(seg_path, "wb")
    sw.setnchannels(nchannels)
    sw.setsampwidth(sampwidth)
    sw.setframerate(sample_rate)
    sw.writeframes(raw)
    sw.close()


def transcribe_segmented(
    audio_path,
    output_path,
    segment_s=300,
    model_size="small",
    device="cuda",
    compute_type="float16",
    language="zh",
    beam_size=5,
):
    """Transcribe a long audio file by splitting into segments.

    Args:
        audio_path: Path to 16kHz mono WAV file.
        output_path: Where to write the merged transcript.
        segment_s: Seconds per segment (default 300).
        model_size: faster-whisper model size.
        device: "cuda" or "cpu".
        compute_type: "float16", "int8", etc.
        language: Language code.
        beam_size: Beam size for decoding.

    Returns:
        output_path on success.

    Raises:
        RuntimeError if transcription fails.
    """
    from faster_whisper import WhisperModel

    sample_rate, nchannels, sampwidth, total_frames = _read_audio_params(audio_path)
    total_duration = total_frames / sample_rate
    frames_per_seg = sample_rate * segment_s
    num_segments = int(total_duration // segment_s) + (1 if total_duration % segment_s > 0 else 0)

    print(f"  Audio: {total_duration:.0f}s, {num_segments} segment(s) of ~{segment_s}s")
    print(f"  Model: faster-whisper {model_size} ({device}, {compute_type})")

    model = WhisperModel(model_size, device=device, compute_type=compute_type)

    media_dir = os.path.dirname(audio_path)
    all_lines = []
    total_elapsed = 0.0

    for i in range(num_segments):
        start_frame = i * frames_per_seg
        nframes = min(frames_per_seg, total_frames - start_frame)
        dur = nframes / sample_rate
        seg_offset = i * segment_s

        seg_path = os.path.join(media_dir, f"_seg_{i:03d}.wav")
        _write_segment(audio_path, start_frame, nframes, nchannels, sampwidth, sample_rate, seg_path)

        print(f"  [{i+1}/{num_segments}] {dur:.0f}s @ offset {seg_offset}s ...", end=" ", flush=True)
        t0 = time.time()

        seg_lines, _ = model.transcribe(seg_path, language=language, beam_size=beam_size)

        seg_texts = []
        for seg in seg_lines:
            global_start = seg_offset + seg.start
            global_end = seg_offset + seg.end
            seg_texts.append(f"[{global_start:.1f}s -> {global_end:.1f}s] {seg.text.strip()}")

        all_lines.append(f"=== Segment {i+1} (offset: {seg_offset}s) ===\n")
        all_lines.append("\n".join(seg_texts) + "\n")

        os.remove(seg_path)
        elapsed = time.time() - t0
        total_elapsed += elapsed
        print(f"{len(seg_texts)} lines, {elapsed:.0f}s")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_lines))

    print(f"  Done. {num_segments} segments in {total_elapsed:.0f}s -> {output_path}")
    return output_path


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python transcribe_segmented.py <input.wav> <output.txt> [segment_s]")
        sys.exit(1)

    input_path = sys.argv[1]
    out_path = sys.argv[2]
    seg_s = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    transcribe_segmented(input_path, out_path, segment_s=seg_s)
