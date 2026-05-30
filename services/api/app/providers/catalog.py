from ..models import BgmTrack, VoiceProfile


BUILT_IN_VOICES = [
    VoiceProfile(voice_id="default-female", name="清澈女声", description="适合种草、情绪价值、生活方式口播"),
    VoiceProfile(voice_id="default-male", name="沉稳男声", description="适合知识口播、测评、商业解说"),
    VoiceProfile(voice_id="energetic", name="活力主播", description="适合带货、促销、节奏快的视频"),
]

BUILT_IN_BGM = [
    BgmTrack(bgm_id="default-light", name="轻快日常", mood="light"),
    BgmTrack(bgm_id="default-tech", name="科技律动", mood="tech"),
    BgmTrack(bgm_id="default-warm", name="温暖叙事", mood="warm"),
]
