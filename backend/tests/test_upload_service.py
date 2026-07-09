from types import SimpleNamespace

from travel_agent.services.upload_service import extract_upload_context


def test_extract_txt_upload():
    upload = SimpleNamespace(filename='note.txt', content_type='text/plain')
    context = extract_upload_context(upload, '你好\n世界'.encode('utf-8'))
    assert context['file_kind'] == 'text'
    assert '你好' in context['extracted_text']


def test_extract_markdown_upload():
    upload = SimpleNamespace(filename='plan.md', content_type='text/markdown')
    context = extract_upload_context(upload, b'# Title\n\nbody')
    assert context['file_kind'] == 'text'
    assert 'Title' in context['extracted_text']
