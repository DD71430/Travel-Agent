from __future__ import annotations

import base64
import json
import mimetypes
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import websocket

from travel_agent.core.config import get_settings
from travel_agent.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


def ffmpeg_binary() -> str:
    configured = getattr(settings, 'ffmpeg_path', '') or ''
    if configured and Path(configured).exists():
        return configured
    for candidate in (Path(r'D:\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe'), Path(r'D:\ffmpeg\bin\ffmpeg.exe'), Path(r'C:\ffmpeg\bin\ffmpeg.exe')):
        if candidate.exists():
            return str(candidate)
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        logger.debug('Failed to resolve bundled ffmpeg from imageio-ffmpeg', exc_info=True)
    else:
        if bundled and Path(bundled).exists():
            return str(bundled)
    return 'ffmpeg'


def _safe_debug(debug: dict[str, Any], transcript: str = '') -> dict[str, Any]:
    allowed = {'stage', 'error_type', 'error_message', 'input_size', 'converted_size', 'transcript_preview', 'result_type', 'session_updated_seen'}
    filtered = {key: value for key, value in debug.items() if key in allowed}
    if transcript and 'transcript_preview' not in filtered:
        filtered['transcript_preview'] = transcript[:120]
    return filtered


def transcribe_audio(filename: str, content: bytes, content_type: str | None) -> tuple[str, str, dict[str, Any]]:
    debug: dict[str, Any] = {'stage': 'start', 'input_size': len(content)}
    if not settings.qwen_api_key:
        debug['stage'] = 'missing_api_key'
        return '', 'missing_api_key', _safe_debug(debug)
    suffix = Path(filename or 'audio').suffix.lower() or '.mp3'
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_file.write(content)
    temp_file.flush()
    temp_file.close()
    temp_path = Path(temp_file.name)
    wav_path: Path | None = None
    pcm_path: Path | None = None
    try:
        debug['content_type'] = content_type or mimetypes.guess_type(filename or temp_path.name)[0] or 'audio/mpeg'
        wav_file = tempfile.NamedTemporaryFile(delete=False, suffix='.wav')
        wav_file.close()
        wav_path = Path(wav_file.name)
        pcm_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pcm')
        pcm_file.close()
        pcm_path = Path(pcm_file.name)
        try:
            subprocess.run([ffmpeg_binary(), '-y', '-i', str(temp_path), '-ac', '1', '-ar', str(settings.fun_asr_sample_rate), '-f', 'wav', str(wav_path)], check=True, capture_output=True)
            subprocess.run([ffmpeg_binary(), '-y', '-i', str(wav_path), '-ac', '1', '-ar', str(settings.fun_asr_sample_rate), '-f', 's16le', '-acodec', 'pcm_s16le', str(pcm_path)], check=True, capture_output=True)
        except Exception as exc:
            logger.exception('Audio conversion failed')
            debug.update({'stage': 'convert', 'error_type': exc.__class__.__name__, 'error_message': 'pcm_convert_failed'})
            return '', 'pcm_convert_failed', _safe_debug(debug)
        pcm_bytes = pcm_path.read_bytes() if pcm_path.exists() else b''
        debug['converted_size'] = len(pcm_bytes)
        if not pcm_bytes:
            debug.update({'stage': 'convert', 'error_type': 'PCMConversionError', 'error_message': 'empty_pcm_output'})
            return '', 'empty_pcm_output', _safe_debug(debug)
        workspace_id = settings.dashscope_workspace_id.strip()
        if not workspace_id:
            debug['stage'] = 'missing_workspace_id'
            return '', 'missing_workspace_id', _safe_debug(debug)
        ws_url = f'wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/realtime?model=qwen3-asr-flash-realtime'
        event_counter = 0

        def next_event_id() -> str:
            nonlocal event_counter
            event_counter += 1
            return f'event_{event_counter}'

        headers = [f'Authorization: Bearer {settings.qwen_api_key}', f'X-DashScope-WorkSpace: {workspace_id}']
        ws = websocket.create_connection(ws_url, header=headers, timeout=30)
        try:
            ws.send(json.dumps({'event_id': next_event_id(), 'type': 'session.update', 'session': {'input_audio_format': 'pcm', 'sample_rate': settings.fun_asr_sample_rate, 'input_audio_transcription': {'language': settings.fun_asr_language_hint}, 'turn_detection': None}}, ensure_ascii=False))
            transcript_parts: list[str] = []
            audio_sent = False
            session_updated_seen = False
            while True:
                raw_message = ws.recv()
                if raw_message is None:
                    break
                try:
                    event_payload = json.loads(raw_message)
                except json.JSONDecodeError:
                    continue
                event_type = event_payload.get('type') if isinstance(event_payload, dict) else None
                if event_type == 'session.updated' and not audio_sent:
                    session_updated_seen = True
                    for index in range(0, len(pcm_bytes), 3200):
                        chunk = pcm_bytes[index:index + 3200]
                        if chunk:
                            ws.send(json.dumps({'event_id': next_event_id(), 'type': 'input_audio_buffer.append', 'audio': base64.b64encode(chunk).decode('utf-8')}, ensure_ascii=False))
                    audio_sent = True
                    ws.send(json.dumps({'event_id': next_event_id(), 'type': 'input_audio_buffer.commit'}, ensure_ascii=False))
                    ws.send(json.dumps({'event_id': next_event_id(), 'type': 'session.finish'}, ensure_ascii=False))
                elif event_type == 'conversation.item.input_audio_transcription.text':
                    preview = f"{event_payload.get('text') or ''}{event_payload.get('stash') or ''}".strip()
                    if preview:
                        transcript_parts.append(preview)
                elif event_type == 'conversation.item.input_audio_transcription.completed':
                    transcript = str(event_payload.get('transcript') or '').strip()
                    if transcript:
                        transcript_parts.append(transcript)
                elif event_type == 'session.finished':
                    break
                elif event_type == 'error':
                    error_obj = event_payload.get('error', {}) if isinstance(event_payload, dict) else {}
                    debug.update({'stage': 'websocket', 'error_type': str(error_obj.get('type') or 'error'), 'error_message': str(error_obj.get('message') or 'task failed')})
                    return '', debug['error_message'], _safe_debug(debug)
            if transcript_parts:
                transcript = ''.join(transcript_parts).strip()[: settings.max_extract_chars]
                debug.update({'stage': 'done', 'result_type': 'transcription.completed', 'session_updated_seen': session_updated_seen, 'transcript_preview': transcript[:120]})
                return transcript, '', _safe_debug(debug, transcript)
            debug.update({'stage': 'websocket', 'error_type': 'RecognitionError', 'error_message': 'empty_transcription_response'})
            return '', 'empty_transcription_response', _safe_debug(debug)
        finally:
            try:
                ws.close()
            except Exception:
                logger.debug('Failed to close websocket', exc_info=True)
    except Exception as exc:
        logger.exception('Audio transcription failed')
        debug.update({'stage': 'transcribe', 'error_type': exc.__class__.__name__, 'error_message': str(exc)})
        return '', f'{exc.__class__.__name__}: {exc}', _safe_debug(debug)
    finally:
        for path in (temp_path, wav_path, pcm_path):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.debug('Failed to remove temp audio file', exc_info=True)
