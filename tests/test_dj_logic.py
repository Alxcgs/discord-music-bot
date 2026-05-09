import pytest
from discord_music_bot.services.dj_service import DJService

@pytest.fixture
def dj_service():
    return DJService()

def test_generate_comment_basic(dj_service):
    context = {'title': 'Song A', 'queue_size': 5}
    res = dj_service.generate_comment('chill', context=context)
    assert 'Song A' in res
    assert '5' in res

def test_generate_comment_persona_fallback(dj_service):
    context = {'title': 'Song B'}
    res = dj_service.generate_comment('non_existent', context=context)
    # Should fallback to chill
    assert 'Song B' in res

def test_generate_comment_time_aware(dj_service):
    # Night
    res_night = dj_service.generate_comment('chill', context={'hour': 23})
    assert 'Нічний режим' in res_night
    
    # Morning
    res_morning = dj_service.generate_comment('chill', context={'hour': 8})
    assert 'Ранковий заряд' in res_morning

def test_generate_comment_skips(dj_service):
    res = dj_service.generate_comment('chill', context={'recent_skips': 3})
    assert 'Бачу скіпи' in res

def test_generate_comment_all_personas(dj_service):
    context = {'title': 'T', 'queue_size': 1}
    for persona in ['chill', 'energetic', 'funny']:
        res = dj_service.generate_comment(persona, context=context)
        assert 'T' in res
        assert '1' in res
